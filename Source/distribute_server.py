#! python3.3
from multiprocessing.connection import Listener, Client
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

def work(server, conn, remote_endpoint, counter):
    try:
        accept = server.accept()
        with conn:
            conn.send("ACCEPT" if accept else "REJECT")
            if not accept:
                return
            try:
                counter.inc()
                task = conn.recv()
                task.server_process(server, conn, remote_endpoint)
            finally:
                counter.dec()
    except:
        import traceback
        traceback.print_exc()

class ServerManager(SyncManager):
    pass

class FileRepository:
    def __init__(self):
        self.__dir = tempfile.mkdtemp()
        self.__lock = ThreadLock()
        self.__files = {}

    def acquire(self):
        self.__lock.acquire()

    def release(self):
        self.__lock.release()

    def register_file(self, filename, size, last_modified):
        if filename in self.__files:
            size, path, local = self.__files[filename]
            os.remove(local)
        ext = os.path.splitext(filename)[1]
        handle, local_filename = tempfile.mkstemp(dir=self.__dir, suffix=ext)
        self.__files[filename] = size, last_modified, local_filename
        os.close(handle)
        return local_filename

    def check_file(self, remote_filename, size, last_modified):
        if not remote_filename in self.__files:
            return None
        l_size, l_last_modified, l_path = self.__files[remote_filename]
        if l_size != size or l_last_modified != last_modified:
            del self.__files[remote_filename]

        return l_path

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

ServerManager.register('FileRepository', FileRepository)
ServerManager.register('Counter', Counter)


class ServerCompiler:
    def __init__(self, file_repository, cpu_usage_hwm=None):
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
            setup = msvc.MSVCDistributer.setup_compiler(compiler_info)
            if setup:
                self.__compiler_setup[compiler_info]=setup
            return setup
        else:
            raise RuntimeError("Unknown toolset '{}'".format(self.__compiler_info.toolset()))

class ServerRunner(Process):
    def __init__(self, port, processes, shutdown_event, task_counter, file_repository, cpu_usage_hwm=None):
        super(ServerRunner, self).__init__()
        print("Starting server on port {} with {} worker processes.".format(
            port, processes))
        if cpu_usage_hwm:
            print("CPU usage hwm is {}%.".format(cpu_usage_hwm))
        self.__port = port
        self.__processes = processes
        self.__shutdown_event = shutdown_event

        self.__compiler = ServerCompiler(file_repository, cpu_usage_hwm)
        self.__tasks = task_counter

    def run(self):
        with Listener(('', self.__port), 'AF_INET') as listener, Pool(processes=self.__processes) as pool:
            while True:
                try:
                    conn = listener.accept()
                    if self.__shutdown_event.is_set():
                        break
                    pool.apply_async(func=work, args=(self.__compiler,
                        conn, listener.last_accepted, self.__tasks))
                except Exception:
                    pass
   
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
    
        shutdown_event = Event()
        server_runner = ServerRunner(port, processes, shutdown_event, task_counter, file_repository, cpu_usage_hwm)
        server_runner.start()

        try:
            while True:
                sys.stdout.write("Running {} tasks.\r".format(task_counter.get()))
                sleep(1)
        except KeyboardInterrupt:
            pass
            #import traceback
            #traceback.print_exc()

        shutdown_event.set()
        # Wake up listener accept
        Client(('127.0.0.1', port), 'AF_INET')
        server_runner.join()





    

