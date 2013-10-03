#! python3.3
from multiprocessing import Manager, Pool, Lock, Process, Event
from multiprocessing.managers import SyncManager
from time import sleep, time
from threading import Lock as ThreadLock
from io import BytesIO
from utils import bind_to_random_port, SimpleTimer

import configparser
import os
import pickle
import psutil
import sys
import tempfile
import traceback
import tarfile
import shutil
import zlib
import zmq
#import cProfile

from Messaging import ServerSession, ServerWorker, Broker

from utils import TempFile, send_compressed_file

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
            import msvc
            setup = msvc.MSVCWrapper.setup_compiler(compiler_info)
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

    def __init__(self, file_repository, cpu_usage_hwm, task_counter,
                 compiler_setup, include_path, headers):
        ServerCompiler.__init__(self, file_repository, compiler_setup,
                                cpu_usage_hwm)
        self.state = self.STATE_START
        self.header_state = self.STATE_WAITING_FOR_HEADER_LIST
        self.task_counter = task_counter
        self.compiler_setup = compiler_setup
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

    def setup_include_dirs(self, fileobj):
        dir_setup_timer = SimpleTimer()
        self.times['tar_extract'] = dir_setup_timer.get()
        with tarfile.open(fileobj=fileobj, mode='r') as tar:
            for tarinfo in tar.getmembers():
                # Additional dirs are needed on the path.
                if tarinfo.name == 'include_paths.txt':
                    include_dir_reader = tar.extractfile(tarinfo)
                    include_dirs = include_dir_reader.read().split(b'\n')
                    for include_dir in include_dirs:
                        assert not os.path.isabs(include_dir)
                        self.include_dirs.append(
                            os.path.normpath(os.path.join(self.include_path,
                                                          include_dir.decode())))
                elif tarinfo.name in self.headers and \
                    self.headers[tarinfo.name] == tarinfo.size:
                    continue
                self.headers[tarinfo.name] = tarinfo.size
                tar.extract(tarinfo, path=self.include_path)
        self.times['setup_include_dir'] = dir_setup_timer.get()

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
            in_tar_buf = BytesIO(msg[1])
            self.times['preprocessing.internal'] = pickle.loads(msg[2])
            out_tar_buf = BytesIO()
            with tarfile.open(mode='r', fileobj=in_tar_buf) as in_tar, \
                tarfile.open(mode='w', fileobj=out_tar_buf) as out_tar:
                for tar_info in in_tar.getmembers():
                    if not tar_info.name in self.headers:
                        out_tar.addfile(tar_info)
                    elif self.headers[tar_info.name] != tar_info.size:
                        out_tar.addfile(tar_info)
            out_tar_buf.seek(0)
            socket.send_multipart([b'REQUIRED_FILES', out_tar_buf.read()])
            self.header_state = self.STATE_WAITING_FOR_HEADERS
            return False, False
        elif self.header_state == self.STATE_WAITING_FOR_HEADERS:
            assert msg[0] == b'TASK_FILES'
            tar_data = msg[1]
            archive_desc = BytesIO(tar_data)
            archive_desc.seek(0)
            self.setup_include_dirs(archive_desc)
            del archive_desc
            self.header_state = self.STATE_HEADERS_ARRIVED
            if self.state == self.STATE_SH_WAIT_FOR_TASK_DATA:
                self.run_compiler()
                self.task_counter.dec()
                return True, True
            return True, False




class ServerManager(SyncManager):
    pass

class FileRepository:
    def __init__(self):
        self.__dir = tempfile.mkdtemp()
        self.__lock = ThreadLock()
        self.__files = {}
        self.__partial_files = {}

    def __del__(self):
        shutil.rmtree(self.__dir)

    def register_file(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            if key in self.__files:
                return self.__files[key], False
            if key in self.__partial_files:
                return self.__partial_files[key], False
            ext = os.path.splitext(filename)[1]
            handle, local_filename = tempfile.mkstemp(dir=self.__dir, suffix=ext)
            os.close(handle)
            self.__partial_files[key] = local_filename
            return local_filename, True

    def file_arrived(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            return key in self.__files

    def file_completed(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            self.__files[key] = self.__partial_files[key]
            del self.__partial_files[key]

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

ServerManager.register('FileRepository', FileRepository)
ServerManager.register('Counter', Counter)

class CompileWorker(Process):
    def __init__(self, address, control_address, file_repository, cpu_usage_hwm,
                 task_counter):
        Process.__init__(self)
        self.__address = address
        self.__control_address = control_address
        self.__file_repository = file_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter
        self.__include_path = tempfile.mkdtemp(suffix='', prefix='tmp',
                                               dir=None)
        self.__headers = {}

    class SessionMaker:
        def __init__(self, file_repository, cpu_usage_hwm, task_counter,
                     compiler_setup, include_path, headers):
            self.__file_repository = file_repository
            self.__cpu_usage_hwm = cpu_usage_hwm
            self.__task_counter = task_counter
            self.__compiler_setup = compiler_setup
            self.__include_path = include_path
            self.__headers = headers

        def __call__(self):
            return CompileSession(self.__file_repository, self.__cpu_usage_hwm,
                                  self.__task_counter, self.__compiler_setup,
                                  self.__include_path, self.__headers)

    def run(self):
        #profile = cProfile.Profile()
        #profile.enable()
        compiler_setup = {}
        try:
            worker = ServerWorker(zmq.Context(), CompileWorker.SessionMaker(
                                    self.__file_repository,
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
            #profile.disable()
            #profile.print_stats()

class ServerRunner(Process):
    def __init__(self, port, control_port, processes, file_repository,
                 cpu_usage_hwm, task_counter):
        super(ServerRunner, self).__init__()
        print("Starting server on port {} with {} worker processes.".format(
            port, processes))
        if cpu_usage_hwm:
            print("CPU usage hwm is {}%.".format(cpu_usage_hwm))
        self.__port = port
        self.__processes = processes
        self.__control_address = 'tcp://localhost:{}'.format(control_port)
        self.__file_repository = file_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter

    def run(self):
        broker = Broker(zmq.Context())
        broker.bind_clients('tcp://*:{}'.format(self.__port))
        broker.connect_control(self.__control_address)
        worker_address = 'tcp://localhost:{}'.format(
            bind_to_random_port(broker.servers))
        workers = list((CompileWorker(worker_address, self.__control_address,
            self.__file_repository, self.__cpu_usage_hwm, self.__task_counter)
            for proc in range(self.__processes)))
        for worker in workers:
            worker.start()
        broker.run()
        for worker in workers:
            worker.join()
   
default_script = 'distribute_server.ini'

if __name__ == "__main__":
    if len(sys.argv) == 2:
        iniFile = os.path.join(os.getcwd(), sys.argv[1])
    else:
        iniFile = os.path.join(os.getcwd(), default_script)
    if not os.path.isfile(iniFile):
        print("""
Usage:
    {} [<ini-file>]

    If no <ini-file> is specified, script will attept to use '{}'
    in the current directory.
""").format(sys.argv[0], default_script)
        raise Exception("Ini file not found")

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(iniFile):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(iniFile))

    server_section = 'Server'
    port = config.getint(server_section, 'port')
    processes = config.getint(server_section, 'processes')

    cpu_usage_hwm = config.getint(server_section, 'cpu_usage_hwm', fallback=None)
    if cpu_usage_hwm is not None:
        assert isinstance(cpu_usage_hwm, int)
        if cpu_usage_hwm <= 0 or cpu_usage_hwm > 100:
            raise RuntimeError("cpu_usage_hwm should be in range 1-100.")
    with ServerManager() as manager:
        task_counter = manager.Counter()
        file_repository = manager.FileRepository()

        zmq_ctx = zmq.Context()
        control = zmq_ctx.socket(zmq.PUB)
        control_port = bind_to_random_port(control)
        server_runner = ServerRunner(port, control_port,
            processes, file_repository, cpu_usage_hwm, task_counter)
        server_runner.start()

        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        try:
            while True:
                sys.stdout.write("Running {} tasks.\r".format(task_counter.get()))
                sleep(1)
        except KeyboardInterrupt:
            pass

        control.send(b'SHUTDOWN')
        server_runner.join()

