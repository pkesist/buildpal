from .Messaging import ServerSession, ServerWorker
from Common import send_compressed_file, SimpleTimer

from io import BytesIO
from multiprocessing import Process
from time import sleep, time
from socket import getfqdn
import subprocess

import os
import pickle
import psutil
import shutil
import sys
import tarfile
import tempfile
import zipfile
import zlib
import zmq

try:
    # Dummy call to test whether symlinks are supported.
    make_link = os.symlink
    make_link('', '')
except NotImplementedError:
    make_link = os.link
except FileNotFoundError:
    pass

class CompileSession(ServerSession):
    STATE_START = 0
    STATE_GET_TASK = 1
    STATE_DONE = 2
    STATE_SH_WAIT_FOR_TASK_DATA = 3
    STATE_WAITING_FOR_COMPILER = 4
    STATE_SH_GET_SOURCE_FILE_NAME = 5
    STATE_SH_CHECK_PCH_TAG = 6
    STATE_SH_GET_PCH_DATA = 7

    STATE_WAITING_FOR_HEADER_LIST = 0
    STATE_WAITING_FOR_HEADERS = 1
    STATE_HEADERS_ARRIVED = 2

    def __init__(self, file_repository, header_repository, compiler_repository,
                 run_compiler_sem, cpu_usage_hwm, task_counter, include_path,
                 checksums):
        self.state = self.STATE_START
        self.header_state = self.STATE_WAITING_FOR_HEADER_LIST
        self.task_counter = task_counter
        self.compiler_repository = compiler_repository
        self.header_repository = header_repository
        self.file_repository = file_repository
        self.run_compiler_sem = run_compiler_sem
        self.cpu_usage_hwm = cpu_usage_hwm
        self.include_path = include_path
        self.include_dirs = [self.include_path]
        self.checksums = checksums
        self.times = {}

    def created(self):
        assert self.state == self.STATE_START
        accept_task = not self.cpu_usage_hwm or psutil.cpu_percent() < self.cpu_usage_hwm
        self.send_pyobj('ACCEPT' if accept_task else 'REJECT')
        self.state = self.STATE_GET_TASK if accept_task else self.STATE_DONE
        return accept_task

    def run_compiler(self):
        self.source_file = os.path.join(self.include_path, self.task['source'])
        if self.task['pch_file'] is not None:
            while not self.file_repository.file_arrived(
                *self.task['pch_file']):
                # The PCH file is being downloaded by another session.
                # This could be made prettier by introducing another state
                # in this state machine. However, wake-up event for that
                # state would require inter-session communication.
                # Just not worth the additional complexity.
                sleep(1)

        object_file_handle, object_file_name = tempfile.mkstemp(suffix='.obj')
        os.close(object_file_handle)
        compiler_info = self.task['compiler_info']
        noLink = compiler_info.compile_no_link_option.make_value().make_str()
        output = compiler_info.object_name_option.make_value(
            object_file_name).make_str()
        pch_switch = []
        if self.task['pch_file']:
            assert self.pch_file is not None
            assert os.path.exists(self.pch_file)
            pch_switch.append(
                compiler_info.pch_file_option.make_value(self.pch_file).make_str())

        while not self.compiler_repository.has_compiler(self.compiler_id):
            # Compiler is being downloaded by another session.
            # Similar to the PCH hack above.
            sleep(1)

        try:
            start = time()
            command = (self.task['call'] + pch_switch +
                [noLink, output] +
                [compiler_info.include_option.make_value(incpath).make_str()
                    for incpath in self.include_dirs] +
                [self.source_file])
            with self.run_compiler_sem:
                retcode, stdout, stderr = self.compiler(command,
                                                        self.include_path)
        except Exception:
            self.send(b'SERVER_FAILED')
            import traceback
            traceback.print_exc()
            return
        done = time()
        self.times['compiler'] = done - start
        self.send_multipart([b'SERVER_DONE', pickle.dumps((retcode,
            stdout, stderr, self.times))])
        if retcode == 0:
            with open(object_file_name, 'rb') as obj:
                send_compressed_file(self.send_multipart, obj, copy=False)

    def compiler_ready(self):
        assert hasattr(self, 'compiler_id')
        self.compiler_exe = os.path.join(
            self.compiler_repository.compiler_dir(self.compiler_id),
            self.task['compiler_info'].executable())
        def run_compiler(command, cwd):
            command[0] = self.compiler_exe
            with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        self.compiler = run_compiler
        self.task_counter.inc()
        if self.task['pch_file'] is None:
            if self.header_state == self.STATE_HEADERS_ARRIVED:
                self.run_compiler()
                return True
            else:
                self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
                return False
        self.state = self.STATE_SH_CHECK_PCH_TAG
        return False

    def process_msg_worker(self, msg):
        if self.state == self.STATE_GET_TASK:
            self.waiting_for_header_list = SimpleTimer()
            self.task = pickle.loads(msg[0])
            self.compiler_id = self.task['compiler_info'].id()
            assert self.compiler_id
            has_compiler = self.compiler_repository.has_compiler(self.compiler_id)
            if has_compiler is None:
                # Never heard of it.
                self.send(b'NEED_COMPILER')
                self.state = self.STATE_WAITING_FOR_COMPILER
                self.compiler_data = BytesIO()
            else:
                self.send(b'READY')
                return self.compiler_ready()
        elif self.state == self.STATE_WAITING_FOR_COMPILER:
            more, data = msg
            self.compiler_data.write(data)
            if more == b'\x00':
                self.compiler_data.seek(0)
                with zipfile.ZipFile(self.compiler_data) as zip:
                    zip.extractall(path=self.compiler_repository.compiler_dir(self.compiler_id))
                del self.compiler_data
                self.compiler_repository.set_compiler_ready(self.compiler_id)
                return self.compiler_ready()
        elif self.state == self.STATE_SH_CHECK_PCH_TAG:
            tag = msg[0]
            assert tag == b'NEED_PCH_FILE'
            self.pch_file, required = self.file_repository.register_file(
                *self.task['pch_file'])
            if required:
                self.send(b'YES')
                self.pch_desc = open(self.pch_file, 'wb')
                self.pch_decompressor = zlib.decompressobj()
                self.state = self.STATE_SH_GET_PCH_DATA
            else:
                self.send(b'NO')
                if self.header_state == self.STATE_HEADERS_ARRIVED:
                    self.run_compiler()
                    return True
                else:
                    self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        elif self.state == self.STATE_SH_GET_PCH_DATA:
            more, data = msg
            self.pch_desc.write(self.pch_decompressor.decompress(data))
            if more == b'\x00':
                self.pch_desc.write(self.pch_decompressor.flush())
                self.pch_desc.close()
                del self.pch_desc
                del self.pch_decompressor
                self.file_repository.file_completed(*self.task['pch_file'])
                if self.header_state == self.STATE_HEADERS_ARRIVED:
                    self.run_compiler()
                    return True
                else:
                    self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        else:
            raise Exception("Invalid state.")
        return False

    def process_msg(self, msg):
        result = self.process_msg_worker(msg)
        if result:
            self.task_counter.dec()
        return result

    def process_attached_msg(self, socket, msg):
        if self.header_state == self.STATE_WAITING_FOR_HEADER_LIST:
            if hasattr(self, 'waiting_for_header_list'):
                self.times['wait_for_header_list'] = self.waiting_for_header_list.get()
                del self.waiting_for_header_list
            else:
                self.times['wait_for_header_list'] = 0
            self.wait_for_headers = SimpleTimer()
            assert msg[0] == b'TASK_FILE_LIST'
            filelist = pickle.loads(msg[1])
            missing_files, self.repo_transaction_id = self.header_repository.missing_files(getfqdn(), filelist)
            socket.send_multipart([b'MISSING_FILES', pickle.dumps(missing_files)])
            self.header_state = self.STATE_WAITING_FOR_HEADERS
            return False, False
        elif self.header_state == self.STATE_WAITING_FOR_HEADERS:
            self.times['wait_for_headers'] = self.wait_for_headers.get()
            del self.wait_for_headers
            assert msg[0] == b'TASK_FILES'
            tar_data = msg[1]
            shared_prepare_dir_timer = SimpleTimer()
            self.include_dirs = self.header_repository.prepare_dir(getfqdn(), tar_data, self.repo_transaction_id, self.include_path)
            self.times['shared_prepare_dir'] = shared_prepare_dir_timer.get()
            del shared_prepare_dir_timer
            self.header_state = self.STATE_HEADERS_ARRIVED
            if self.state == self.STATE_SH_WAIT_FOR_TASK_DATA:
                self.run_compiler()
                self.task_counter.dec()
                return True, True
            return True, False

class CompileWorker(Process):
    def __init__(self, address, control_address, file_repository,
        header_repository, compiler_repository, run_compiler_sem, cpu_usage_hwm,
        task_counter):
        Process.__init__(self)
        self.__address = address
        self.__control_address = control_address
        self.__file_repository = file_repository
        self.__header_repository = header_repository
        self.__compiler_repository = compiler_repository
        self.__run_compiler_sem = run_compiler_sem
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter
        self.__include_path = tempfile.mkdtemp(suffix='', prefix='tmp',
                                               dir=None)
        self.__checksums = {}

    class SessionMaker:
        def __init__(self, file_repository, header_repository,
            compiler_repository, compiler_sem, cpu_usage_hwm, task_counter,
            include_path, checksums):
            self.__file_repository = file_repository
            self.__header_repository = header_repository
            self.__compiler_repository = compiler_repository
            self.__run_compiler_sem = compiler_sem
            self.__cpu_usage_hwm = cpu_usage_hwm
            self.__task_counter = task_counter
            self.__include_path = include_path
            self.__checksums = checksums

        def __call__(self):
            return CompileSession(self.__file_repository,
                self.__header_repository, self.__compiler_repository,
                self.__run_compiler_sem, self.__cpu_usage_hwm,
                self.__task_counter, self.__include_path, self.__checksums)

    def run(self):
        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
        try:
            worker = ServerWorker(zmq.Context(), CompileWorker.SessionMaker(
                self.__file_repository, self.__header_repository,
                self.__compiler_repository, self.__run_compiler_sem,
                self.__cpu_usage_hwm, self.__task_counter, self.__include_path,
                self.__checksums))
            worker.connect_broker(self.__address)
            worker.connect_control(self.__control_address)
            worker.run()
        except KeyboardInterrupt:
            pass
        finally:
            shutil.rmtree(self.__include_path)
