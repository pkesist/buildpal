#! python3.3
from time import sleep

from Common import bind_to_random_port
from Server import CompileWorker
    
from multiprocessing import cpu_count

import configparser
import os
import sys
import zmq

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
""".format(sys.argv[0], default_script))
        raise Exception("Ini file not found")

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(iniFile):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(iniFile))

    server_section = 'Server'
    port = config.getint(server_section, 'port')

    cpu_usage_hwm = config.getint(server_section, 'cpu_usage_hwm', fallback=None)
    if cpu_usage_hwm is not None:
        assert isinstance(cpu_usage_hwm, int)
        if cpu_usage_hwm <= 0 or cpu_usage_hwm > 100:
            raise RuntimeError("cpu_usage_hwm should be in range 1-100.")

    CompileWorker('tcp://*:{}'.format(port), cpu_usage_hwm).run()

