#! python3.3
from multiprocessing import Manager, Pool, Lock, Process, Event
from multiprocessing.managers import SyncManager
from time import sleep, time
from threading import Lock as ThreadLock
from io import BytesIO

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
            raise RuntimeError("Unknown toolset '{}'".format(self.__compiler_info.toolset()))

class CompileSession(ServerSession, ServerCompiler):
    STATE_START = 0
    STATE_GET_TASK = 1
    STATE_DONE = 2
    STATE_SH_GET_ARCHIVE_TAG = 3
    STATE_SH_GET_ARCHIVE_DATA = 4
    STATE_SH_GET_SOURCE_FILE_NAME = 5
    STATE_SH_CHECK_PCH_TAG = 6
    STATE_SH_GET_PCH_DATA = 7

    def __init__(self, file_repository, cpu_usage_hwm, task_counter, compiler_setup):
        ServerCompiler.__init__(self, file_repository, compiler_setup, cpu_usage_hwm)
        self.state = self.STATE_START
        self.task_counter = task_counter
        self.compiler_setup = compiler_setup
        self.include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
        self.include_dirs = [self.include_path]

    def created(self):
        assert self.state == self.STATE_START
        accept = self.accept()
        self.send_pyobj('ACCEPT' if accept else 'REJECT')
        self.state = self.STATE_GET_TASK if accept else self.STATE_DONE
        return accept

    def setup_include_dirs(self, fileobj):
        with tarfile.open(fileobj=fileobj, mode='r') as tar:
            tar.extractall(path=self.include_path)

        include_list = os.path.join(self.include_path, 'include_paths.txt')
        if os.path.exists(include_list):
            for path in open(include_list, 'rt'):
                assert not os.path.isabs(path)
                self.include_dirs.append(os.path.normpath(os.path.join(self.include_path, path)))

    def run_compiler(self):
        try:
            with TempFile(suffix='.obj') as object_file:
                compiler_info = self.task['compiler_info']
                noLink = compiler_info.compile_no_link_option.make_value().make_str()
                output = compiler_info.object_name_option.make_value(object_file.filename()).make_str()
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
                    retcode, stdout, stderr = self.compiler(command, self.include_path)
                except Exception:
                    self.send(b'SERVER_FAILED')
                    import traceback
                    traceback.print_exc()
                    return
                done = time()
                self.send_multipart([b'SERVER_DONE', pickle.dumps((retcode, stdout, stderr, done - start))])
                if retcode == 0:
                    with object_file.open('rb') as obj:
                        send_compressed_file(self.send_multipart, obj, copy=False)
        finally:
            shutil.rmtree(self.include_path, ignore_errors=True)

    def process_msg_worker(self):
        if self.state == self.STATE_GET_TASK:
            self.task = self.recv_pyobj()
            self.compiler = self.setup_compiler(self.task['compiler_info'])
            if self.compiler:
                self.send(b'OK')
            else:
                self.send_pyobj("FAIL")
                return False
            self.task_counter.inc()
            if self.task['pch_file'] is None:
                self.state = self.STATE_SH_GET_ARCHIVE_TAG
            else:
                self.state = self.STATE_SH_CHECK_PCH_TAG
        elif self.state == self.STATE_SH_CHECK_PCH_TAG:
            tag = self.recv_pyobj()
            assert tag == 'NEED_PCH_FILE'
            self.pch_file, required = self.file_repository().register_file(*self.task['pch_file'])
            if required:
                self.send(b'YES')
                self.pch_desc = open(self.pch_file, 'wb')
                self.pch_decompressor = zlib.decompressobj()
                self.state = self.STATE_SH_GET_PCH_DATA
            else:
                self.send(b'NO')
                self.state = self.STATE_SH_GET_ARCHIVE_TAG
        elif self.state == self.STATE_SH_GET_PCH_DATA:
            more, data = self.recv_multipart()
            self.pch_desc.write(self.pch_decompressor.decompress(data))
            if more == b'\x00':
                self.pch_desc.write(self.pch_decompressor.flush())
                self.pch_desc.close()
                del self.pch_desc
                del self.pch_decompressor
                self.file_repository().file_completed(*self.task['pch_file'])
                self.state = self.STATE_SH_GET_ARCHIVE_TAG
        elif self.state == self.STATE_SH_GET_ARCHIVE_TAG:
            archive_tag = self.recv_pyobj()
            assert archive_tag == 'TASK_FILES'
            self.archivedesc = BytesIO()
            self.state = self.STATE_SH_GET_ARCHIVE_DATA
        elif self.state == self.STATE_SH_GET_ARCHIVE_DATA:
            more, data = self.recv_multipart()
            self.archivedesc.write(data)
            if more == b'\x00':
                self.archivedesc.seek(0)
                self.setup_include_dirs(self.archivedesc)
                del self.archivedesc
                self.state = self.STATE_SH_GET_SOURCE_FILE_NAME
        elif self.state == self.STATE_SH_GET_SOURCE_FILE_NAME:
            tag, source_file = self.recv_pyobj()
            assert tag == 'SOURCE_FILE'
            self.source_file = os.path.join(self.include_path, source_file)
            if self.task['pch_file'] is not None:
                while not self.file_repository().file_arrived(*self.task['pch_file']):
                    # The PCH file is being downloaded by another session.
                    # This could be made prettier by introducing another state
                    # in this state machine. However, wake-up event for that
                    # state would require inter-session communication.
                    sleep(1)
            self.run_compiler()
            return True
        return False

    def process_msg(self):
        result = self.process_msg_worker()
        if result:
            self.task_counter.dec()
        return result


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
    def __init__(self, address, control_address, file_repository, cpu_usage_hwm, task_counter):
        Process.__init__(self)
        self.__address = address
        self.__control_address = control_address
        self.__file_repository = file_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter

    class SessionMaker:
        def __init__(self, file_repository, cpu_usage_hwm, task_counter, compiler_setup):
            self.__file_repository = file_repository
            self.__cpu_usage_hwm = cpu_usage_hwm
            self.__task_counter = task_counter
            self.__compiler_setup = compiler_setup

        def __call__(self):
            return CompileSession(self.__file_repository, self.__cpu_usage_hwm, self.__task_counter, self.__compiler_setup)

    def run(self):
        #profile = cProfile.Profile()
        #profile.enable()
        compiler_setup = {}
        try:
            worker = ServerWorker(zmq.Context(), CompileWorker.SessionMaker(self.__file_repository, self.__cpu_usage_hwm, self.__task_counter, compiler_setup))
            worker.connect_broker(self.__address)
            worker.connect_control(self.__control_address)
            worker.run()
        finally:
            pass
            #profile.disable()
            #profile.print_stats()

class ServerRunner(Process):
    def __init__(self, port, control_port, processes, file_repository, cpu_usage_hwm, task_counter):
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
        worker_address = 'tcp://localhost:{}'.format(broker.servers.bind_to_random_port('tcp://*'))
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
        control_port = control.bind_to_random_port('tcp://*')
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

