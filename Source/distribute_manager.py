#! python3.3
from Manager import TaskProcessor

import argparse
import configparser
import os
import sys

default_script = 'distribute_manager.ini'

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Command line parameters for distribute_manager.py')
    parser.add_argument('--ini', dest='ini_file', type=str, default='distribute_manager.ini', help='Specify .ini file.')
    parser.add_argument('profile', type=str, default='Default Profile', help='Profile to use. Must be present in the .ini file.')
    
    opts = parser.parse_args()

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(opts.ini_file):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(opts.ini_file))

    manager_section = 'Manager'

    port = config.get(manager_section, 'port')

    if not opts.profile in config:
        raise "ERROR: No '{}' section in '{}'.".format(opts.profile, opts.ini_file)

    nodes = []
    section = config[opts.profile]
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
