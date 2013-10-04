from .Messaging import ServerSession, ServerWorker
from Common import MSVCWrapper, send_compressed_file, SimpleTimer, TempFile

from io import BytesIO
from multiprocessing import Process
from time import sleep, time

import os
import pickle
import psutil
import shutil
import tarfile
import tempfile
import zlib
import zmq

class ServerCompiler:
    def __init__(self, file_repository, compiler_setup, cpu_usage_hwm):
        self.__hwm = cpu_usage_hwm
        self.__compiler_setup = compiler_setup
        self.__file_repository = file_repository

    def accept(self):
        if not self.__hwm:
            return True
        return psutil.cpu_percent() < self.__hwm

    def file_repository(self):
        return self.__file_repository

    def setup_compiler(self, compiler_info):
        key = (compiler_info.toolset(), compiler_info.id())
        setup = self.__compiler_setup.get(key)
        if setup:
            return setup

        if compiler_info.toolset() == 'msvc':
            setup = MSVCWrapper.setup_compiler(compiler_info)
            if setup:
                self.__compiler_setup[key] = setup
            return setup
        else:
            raise RuntimeError("Unknown toolset '{}'".format(
                                  self.__compiler_info.toolset()))

class CompileSession(ServerSession, ServerCompiler):
    STATE_START = 0
    STATE_GET_TASK = 1
    STATE_DONE = 2
    STATE_SH_WAIT_FOR_TASK_DATA = 3
    STATE_SH_GET_SOURCE_FILE_NAME = 4
    STATE_SH_CHECK_PCH_TAG = 5
    STATE_SH_GET_PCH_DATA = 6

    STATE_WAITING_FOR_HEADER_LIST = 0
    STATE_WAITING_FOR_HEADERS = 1
    STATE_HEADERS_ARRIVED = 2

    def __init__(self, file_repository, header_repository, cpu_usage_hwm, task_counter,
                 compiler_setup, include_path, headers):
        ServerCompiler.__init__(self, file_repository, compiler_setup,
                                cpu_usage_hwm)
        self.state = self.STATE_START
        self.header_state = self.STATE_WAITING_FOR_HEADER_LIST
        self.task_counter = task_counter
        self.compiler_setup = compiler_setup
        self.header_repository = header_repository
        self.include_path = include_path
        self.include_dirs = [self.include_path]
        self.has_task_data = False
        self.times = {}
        self.headers = headers

    def created(self):
        assert self.state == self.STATE_START
        accept = self.accept()
        self.send_pyobj('ACCEPT' if accept else 'REJECT')
        self.state = self.STATE_GET_TASK if accept else self.STATE_DONE
        return accept

    def run_compiler(self):
        self.source_file = os.path.join(self.include_path, self.task['source'])
        if self.task['pch_file'] is not None:
            while not self.file_repository().file_arrived(
                *self.task['pch_file']):
                # The PCH file is being downloaded by another session.
                # This could be made prettier by introducing another state
                # in this state machine. However, wake-up event for that
                # state would require inter-session communication.
                # Just not worth the additional complexity.
                sleep(1)

        with TempFile(suffix='.obj') as object_file:
            compiler_info = self.task['compiler_info']
            noLink = compiler_info.compile_no_link_option.make_value().make_str()
            output = compiler_info.object_name_option.make_value(
                object_file.filename()).make_str()
            pch_switch = []
            if self.task['pch_file']:
                assert self.pch_file is not None
                assert os.path.exists(self.pch_file)
                pch_switch.append(
                    compiler_info.pch_file_option.make_value(self.pch_file).make_str())

            try:
                start = time()
                command = (self.task['call'] + pch_switch +
                    [noLink, output] +
                    [compiler_info.include_option.make_value(incpath).make_str()
                        for incpath in self.include_dirs] +
                    [self.source_file])
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
                with object_file.open('rb') as obj:
                    send_compressed_file(self.send_multipart, obj, copy=False)

    def process_msg_worker(self, msg):
        if self.state == self.STATE_GET_TASK:
            self.task = pickle.loads(msg[0])
            self.compiler = self.setup_compiler(self.task['compiler_info'])
            if self.compiler:
                self.send(b'OK')
            else:
                self.send(b'FAIL')
                return False
            self.task_counter.inc()
            if self.task['pch_file'] is None:
                if self.has_task_data:
                    self.run_compiler()
                    return True
                else:
                    self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
            else:
                self.state = self.STATE_SH_CHECK_PCH_TAG
        elif self.state == self.STATE_SH_CHECK_PCH_TAG:
            tag = msg[0]
            assert tag == b'NEED_PCH_FILE'
            self.pch_file, required = self.file_repository().register_file(
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
                self.file_repository().file_completed(*self.task['pch_file'])
                if self.header_state == self.STATE_HEADERS_ARRIVED:
                    self.run_compiler()
                    return True
                else:
                    self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        else:
            print(self.state, msg)
            assert not "Invalid state"
        return False

    def process_msg(self, msg):
        result = self.process_msg_worker(msg)
        if result:
            self.task_counter.dec()
        return result

    def process_attached_msg(self, socket, msg):
        if self.header_state == self.STATE_WAITING_FOR_HEADER_LIST:
            assert msg[0] == b'TASK_FILE_LIST'
            self.times['preprocessing.internal'] = pickle.loads(msg[2])
            self.filelist = msg[1]
            missing_files = self.header_repository.missing_files(self.filelist)
            socket.send_multipart([b'MISSING_FILES', missing_files])
            self.header_state = self.STATE_WAITING_FOR_HEADERS
            return False, False
        elif self.header_state == self.STATE_WAITING_FOR_HEADERS:
            assert msg[0] == b'TASK_FILES'
            tar_data = msg[1]
            setup_timer = SimpleTimer()
            self.include_dirs = self.header_repository.prepare_dir(tar_data, self.filelist, self.include_path)
            self.times['setup_include_dir'] = setup_timer.get()
            del self.filelist
            self.header_state = self.STATE_HEADERS_ARRIVED
            if self.state == self.STATE_SH_WAIT_FOR_TASK_DATA:
                self.run_compiler()
                self.task_counter.dec()
                return True, True
            return True, False

class CompileWorker(Process):
    def __init__(self, address, control_address, file_repository,
                 header_repository, cpu_usage_hwm, task_counter):
        Process.__init__(self)
        self.__address = address
        self.__control_address = control_address
        self.__file_repository = file_repository
        self.__header_repository = header_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter
        self.__include_path = tempfile.mkdtemp(suffix='', prefix='tmp',
                                               dir=None)
        self.__headers = {}

    class SessionMaker:
        def __init__(self, file_repository, header_repository, cpu_usage_hwm,
                     task_counter, compiler_setup, include_path, headers):
            self.__file_repository = file_repository
            self.__header_repository = header_repository
            self.__cpu_usage_hwm = cpu_usage_hwm
            self.__task_counter = task_counter
            self.__compiler_setup = compiler_setup
            self.__include_path = include_path
            self.__headers = headers

        def __call__(self):
            return CompileSession(self.__file_repository,
                                  self.__header_repository,
                                  self.__cpu_usage_hwm,
                                  self.__task_counter, self.__compiler_setup,
                                  self.__include_path, self.__headers)

    def run(self):
        compiler_setup = {}
        try:
            worker = ServerWorker(zmq.Context(), CompileWorker.SessionMaker(
                                    self.__file_repository,
                                    self.__header_repository,
                                    self.__cpu_usage_hwm,
                                    self.__task_counter,
                                    compiler_setup,
                                    self.__include_path,
                                    self.__headers
                                    ))
            worker.connect_broker(self.__address)
            worker.connect_control(self.__control_address)
            worker.run()
        finally:
            shutil.rmtree(self.__include_path)
