#! python3.3
from multiprocessing import Manager, Pool, Lock, Process, Event
from multiprocessing.managers import SyncManager
from time import sleep
from threading import Lock as ThreadLock

import configparser
import psutil
import tempfile
import traceback
import sys
import os
import zmq
import tarfile
import shutil
import zlib

from Messaging import ServerSession, ServerWorker, Broker

from utils import TempFile, send_compressed_file

class ServerCompiler:
    def __init__(self, file_repository, cpu_usage_hwm):
        self.__hwm = cpu_usage_hwm
        self.__compiler_setup = {}
        self.__file_repository = file_repository

    def accept(self):
        if not self.__hwm:
            return True
        return psutil.cpu_percent() < self.__hwm

    def file_repository(self):
        return self.__file_repository

    def setup_compiler(self, compiler_info):
        setup = self.__compiler_setup.get(compiler_info)
        if setup:
            return setup

        if compiler_info.toolset() == 'msvc':
            import msvc
            setup = msvc.MSVCWrapper.setup_compiler(compiler_info)
            if setup:
                self.__compiler_setup[compiler_info] = setup
            return setup
        else:
            raise RuntimeError("Unknown toolset '{}'".format(self.__compiler_info.toolset()))

class CompileSession(ServerSession, ServerCompiler):
    STATE_START = 0
    STATE_GET_TASK = 1
    STATE_DONE = 2
    STATE_GET_ALGORITHM = 3
    STATE_SH_GET_ARCHIVE_TAG = 4
    STATE_SH_GET_ARCHIVE_DATA = 5
    STATE_SH_GET_SOURCE_TAG = 6
    STATE_SH_GET_SOURCE_DATA = 7
    STATE_SH_CHECK_PCH_TAG = 8
    STATE_SH_GET_PCH_DATA = 9
    STATE_PL_GET_PP_TAG = 10
    STATE_PL_GET_PP_DATA = 11

    def __init__(self, file_repository, cpu_usage_hwm):
        ServerCompiler.__init__(self, file_repository, cpu_usage_hwm)
        self.state = self.STATE_START

    transition_table = {
        STATE_START : {
            True : STATE_GET_TASK,
            False : STATE_DONE },
        STATE_GET_TASK : STATE_GET_ALGORITHM,
        STATE_GET_ALGORITHM : {
            'SCAN_HEADERS' : STATE_SH_GET_ARCHIVE_TAG,
            'PREPROCESS_LOCALLY' : STATE_PL_GET_PP_TAG },
        STATE_SH_GET_ARCHIVE_TAG : STATE_SH_GET_ARCHIVE_DATA,
        STATE_SH_GET_ARCHIVE_DATA : STATE_SH_GET_SOURCE_TAG,
        STATE_SH_GET_SOURCE_TAG : STATE_SH_GET_SOURCE_DATA,
        STATE_SH_GET_SOURCE_DATA : STATE_SH_CHECK_PCH_TAG,
        STATE_SH_CHECK_PCH_TAG : STATE_SH_GET_PCH_DATA,

        STATE_PL_GET_PP_TAG : STATE_PL_GET_PP_DATA }
    
    def next_state(self, data=None):
        if data is None:
            self.state = self.transition_table[self.state]
        else:
            self.state = self.transition_table[self.state][data]

    def created(self):
        assert self.state == self.STATE_START
        accept = self.accept()
        self.send_pyobj('ACCEPT' if accept else 'REJECT')
        self.next_state(accept)
        return accept

    def setup_include_dirs(self):
        self.include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
        with tarfile.open(self.archivefile.filename()) as tar:
            tar.extractall(path=self.include_path)
        os.remove(self.archivefile.filename())
        del self.archivefile
        self.include_dirs = [self.include_path]

        include_list = os.path.join(self.include_path, 'include_paths.txt')
        if os.path.exists(include_list):
            for path in open(include_list, 'rt'):
                assert not os.path.isabs(path)
                self.include_dirs.append(os.path.normpath(os.path.join(self.include_path, path)))

    def run_compiler_with_preprocessed_file(self):
        with self.pp_file as pp_file, TempFile(suffix='.obj') as object_file:
            noLink = self.compile_switch
            output = self.output_switch.format(object_file.filename())
            try:
                retcode, stdout, stderr = self.compiler(self.call +  [noLink, output, pp_file.filename()])
            except Exception:
                self.send_pyobj('SERVER_FAILED')
                return
            self.send_pyobj('SERVER_DONE')
            self.send_pyobj((retcode, stdout, stderr))
            if retcode == 0:
                with object_file.open('rb') as obj:
                    send_compressed_file(self.send_pyobj, obj)

    def run_compiler_with_source_and_headers(self):
        try:
            with TempFile(suffix='.obj') as object_file:
                noLink = self.task.compile_switch
                output = self.task.output_switch.format(object_file.filename())

                compiler_info = self.task.compiler_info
                defines = [compiler_info.define_option.make_value(define).make_str()
                    for define in self.task.preprocessor_info.macros]
                pch_switch = []
                if self.task.pch_file:
                    assert self.pch_file is not None
                    assert os.path.exists(self.pch_file)
                    pch_switch.append(
                        compiler_info.use_pch_option.make_value(self.pch_file).make_str())

                try:
                    command = (self.task.call + defines + pch_switch +
                        [noLink, output] +
                        [compiler_info.include_option.make_value(incpath).make_str()
                            for incpath in self.include_dirs] +
                        [self.source_file.filename()])
                    retcode, stdout, stderr = self.compiler(command)
                except Exception:
                    self.send_pyobj('SERVER_FAILED')
                    import traceback
                    traceback.print_exc()
                    return
                self.send_pyobj('SERVER_DONE')
                self.send_pyobj((retcode, stdout, stderr))
                if retcode == 0:
                    with object_file.open('rb') as obj:
                        send_compressed_file(self.send_pyobj, obj)
        finally:
            shutil.rmtree(self.include_path, ignore_errors=True)

    def process_msg(self):
        if self.state == self.STATE_GET_TASK:
            self.task = self.recv_pyobj()
            self.compiler = self.setup_compiler(self.task.compiler_info)
            if self.compiler:
                self.send_pyobj("OK")
            else:
                self.send_pyobj("FAIL")
                return False
            self.next_state()
        elif self.state == self.STATE_GET_ALGORITHM:
            self.algorithm = self.recv_pyobj()
            self.next_state(self.algorithm)
        elif self.state == self.STATE_SH_GET_ARCHIVE_TAG:
            archive_tag = self.recv_pyobj()
            assert archive_tag == 'HEADERS_ARCHIVE'
            self.archivefile = TempFile()
            self.archivedesc = open(self.archivefile.filename(), 'wb')
            self.next_state()
        elif self.state == self.STATE_SH_GET_ARCHIVE_DATA:
            more, data = self.recv_pyobj()
            self.archivedesc.write(data)
            if not more:
                self.archivedesc.close()
                del self.archivedesc
                self.setup_include_dirs()
                self.next_state()
        elif self.state == self.STATE_SH_GET_SOURCE_TAG:
            tag = self.recv_pyobj()
            assert tag == 'SOURCE_FILE'
            self.source_file = TempFile(suffix=self.task.source_type)
            self.source_desc = open(self.source_file.filename(), 'wb')
            self.source_decompressor = zlib.decompressobj()
            self.next_state()
        elif self.state == self.STATE_SH_GET_SOURCE_DATA:
            more, data = self.recv_pyobj()
            self.source_desc.write(self.source_decompressor.decompress(data))
            if not more:
                self.source_desc.write(self.source_decompressor.flush())
                self.source_desc.close()
                del self.source_desc
                del self.source_decompressor
                if self.task.pch_file is None:
                    self.run_compiler_with_source_and_headers()
                    return True
                else:
                    self.next_state()
        elif self.state == self.STATE_SH_CHECK_PCH_TAG:
            tag = self.recv_pyobj()
            assert tag == 'NEED_PCH_FILE'
            self.pch_file, required = self.file_repository().register_file(*self.task.pch_file)
            if required:
                self.send_pyobj("YES")
                self.pch_desc = open(self.pch_file, 'wb')
                self.pch_decompressor = zlib.decompressobj()
                self.next_state()
            else:
                self.send_pyobj("NO")
                # Ugliness
                while not self.file_repository().file_arrived(*self.task.pch_file):
                    sleep(1)
                self.run_compiler_with_source_and_headers()
                return True
        elif self.state == self.STATE_SH_GET_PCH_DATA:
            more, data = self.recv_pyobj()
            self.pch_desc.write(self.pch_decompressor.decompress(data))
            if not more:
                self.pch_desc.write(self.pch_decompressor.flush())
                self.pch_desc.close()
                del self.pch_desc
                del self.pch_decompressor
                self.file_repository().file_completed(*self.task.pch_file)
                self.run_compiler_with_source_and_headers()
                return True
        elif self.state == self.STATE_PL_GET_PP_TAG:
            tag = self.recv_pyobj()
            assert tag == 'PREPROCESSED_FILE'
            self.pp_file = TempFile()
            self.pp_desc = open(self.pp_file, 'wb')
            self.pp_decompressor = zlib.decompressobj()
            self.next_state()
        elif self.state == self.STATE_PL_GET_PP_DATA:
            more, data = self.recv_pyobj()
            self.pp_desc.write(self.pp_decompressor.decompress(data))
            if not more:
                self.pp_desc.write(self.pp_decompressor.flush())
                self.pp_desc.close()
                del self.pp_desc
                del self.pp_decompressor
                self.run_compiler_with_preprocessed_file()
                return True
        return False

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
    def __init__(self, address, control_address, file_repository, cpu_usage_hwm):
        Process.__init__(self)
        self.__address = address
        self.__control_address = control_address
        self.__file_repository = file_repository
        self.__cpu_usage_hwm = cpu_usage_hwm

    def run(self):
        class SessionMaker:
            def __init__(self, file_repository, cpu_usage_hwm):
                self.__file_repository = file_repository
                self.__cpu_usage_hwm = cpu_usage_hwm

            def __call__(self):
                return CompileSession(self.__file_repository, self.__cpu_usage_hwm)

        worker = ServerWorker(zmq.Context(), SessionMaker(self.__file_repository, self.__cpu_usage_hwm))
        worker.connect_broker(self.__address)
        worker.connect_control(self.__control_address)
        worker.run()

class ServerRunner(Process):
    def __init__(self, port, control_port, processes, file_repository, cpu_usage_hwm=None):
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

    def run(self):
        broker = Broker(zmq.Context())
        broker.bind_clients('tcp://*:{}'.format(self.__port))
        broker.connect_control(self.__control_address)
        worker_address = 'tcp://localhost:{}'.format(broker.servers.bind_to_random_port('tcp://*'))
        workers = list((CompileWorker(worker_address, self.__control_address,
            self.__file_repository, self.__cpu_usage_hwm)
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
        server_runner = ServerRunner(port, control_port, processes, file_repository, cpu_usage_hwm)
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

