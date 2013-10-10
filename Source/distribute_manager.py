#! python3.3
from Manager import TaskProcessor

import configparser
import os
import sys

default_script = 'distribute_manager.ini'

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
        raise SystemExit()

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(iniFile):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(iniFile))

    manager_section = 'Manager'
    nodes_section = 'Build Nodes'

    port = config.get(manager_section, 'port')

    if not nodes_section in config:
        raise "ERROR: No '{}' section in '{}'.".format(nodes_section, iniFile)

    nodes = []
    section = config[nodes_section]
    done = False
    while not done:
        option = "node[{}]".format(len(nodes))
        if option in section:
            value = section[option]
            delim = ':'
            if not delim in value:
                raise RuntimeError("Invalid node value. Node values should be given as <host>:<port>[:<max_tasks>]")
            port_index = value.index(delim)
            try:
                max_tasks_index = value.index(':', port_index + 1)
                server_port = int(value[port_index + 1 : max_tasks_index])
                max_tasks = int(value[max_tasks_index + 1 : ])
            except ValueError:
                server_portport = int(value[port_index + 1:])
                max_tasks = None
            nodes.append({
                'address' : 'tcp://{}:{}'.format(value[:port_index], server_port),
                'max_tasks' : max_tasks })
        else:
            done = True
    if not nodes:
        raise RuntimeError("No build nodes configured.")

    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    try:
        TaskProcessor(nodes, port).run()
    finally:
        print("Shutting down.")
