from multiprocessing.connection import Listener
from multiprocessing import Pool
from multiprocessing.reduction import reduce_connection
import configparser
import traceback
import sys
import os

address = ('', 6070)

def work(conn):
    try:
        conn = conn[0](*conn[1])
        task = conn.recv()
        task.process(conn)
    except:
        print("Failed to execute client task.")
        traceback.print_exc()

def print_tasks():
    global tasks
    sys.stdout.write("Running {} tasks.{}".format(len(tasks), '\r'))

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
    if not server_section in config:
        raise Exception("ERROR: No '{}' section in '{}'.".format(server_section, iniFile))

    section = config[server_section]
    port = 'port'
    if not port in section:
        raise Exception("ERROR: Missing '{}' in '{}' section.".format(id, server_section))
    server_port = int(section[port])
    
    processes = 'processes'
    if not processes in section:
        raise Exception("ERROR: Missing '{}' in '{}' section.".format(id, server_section))
    processes = int(section[processes])

    print("Starting server on port {} with {} worker processes.".format(server_port, processes))
    pool = Pool(processes=processes)
    listener = Listener(('', server_port), 'AF_INET')
    global tasks
    tasks = []
    while True:
        print_tasks()
        conn = listener.accept()
        tasks.append(pool.apply_async(func=work, args=(reduce_connection(conn),)))
        tasks = list(filter(lambda task : not task.ready(), tasks))

        