#! python3
from multiprocessing.connection import Listener
from multiprocessing import Manager, Pool
from multiprocessing.reduction import reduce_connection
import configparser
import psutil
import traceback
import sys
import os

def work(server, conn):
    try:
        conn = conn[0](*conn[1])
        task = conn.recv()
        task.server_process(server, conn)
    except Exception:
        print("Failed to execute client task.")
        traceback.print_exc()

class ServerRunner:
    def __init__(self, port, processes, global_data, cpu_usage_hwm=None):
        print("Starting server on port {} with {} worker processes.".format(
            port, processes))
        if cpu_usage_hwm:
            print("CPU usage hwm is {}%.".format(cpu_usage_hwm))
        self.__pool = Pool(processes = processes)
        self.__listener = Listener(('localhost', port), 'AF_INET')

        self.__tasks = []
        self.__compiler = ServerCompiler(global_data, cpu_usage_hwm)

    def print_tasks(self):
        sys.stdout.write("Running {} tasks.\r".format(len(self.__tasks)))

    def run(self):
        while True:
            self.__tasks = list(filter(lambda task : not task.ready(),
                self.__tasks))
            self.print_tasks()
            conn = self.__listener.accept()
            self.__tasks.append(self.__pool.apply_async(func=work, args=(
                self.__compiler, reduce_connection(conn),)))


class ServerCompiler:
    def __init__(self, global_data, cpu_usage_hwm=None):
        self.__hwm = cpu_usage_hwm
        self.__compiler_setup = {}
        self.__global_data = global_data

        self.__checksum = {}
        self.__include = {}

    def accept(self):
        if not self.__hwm:
            return True
        return psutil.cpu_percent() < self.__hwm

    def local_include_path(self, include_path, checksum):
        if not include_path in self.__global_data:
            return None
        stored_checksum, local_path = self.__global_data[include_path]
        if stored_checksum == checksum:
            return local_path
        return None

    def store_includes(self, include_path, checksum, local_path):
        self.__global_data[include_path] = (checksum, local_path)

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
    if config.has_option(server_section, 'cpu_usage_hwm'):
        cpu_usage_hwm = config.getint(server_section, 'cpu_usage_hwm')
        if cpu_usage_hwm < 0 or cpu_usage_hwm > 100:
            raise RuntimeError("cpu_usage_hwm should be in range 0-100.")
    else:
        cpu_usage_hwm = None
    
    manager = Manager()

    ServerRunner(port, processes, manager.dict(), cpu_usage_hwm).run()
