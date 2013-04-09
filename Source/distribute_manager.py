from multiprocessing.managers import BaseManager

import sys
import os
import configparser

class DistributeManager(BaseManager):
    nodes = None
    last_node = None

    @classmethod
    def _set_nodes(cls, nodes):
        cls.nodes = nodes

    @classmethod
    def _get_node(cls):
        if cls.last_node is not None:
            cls.last_node = (cls.last_node + 1) % len(cls.nodes)
        else:
            cls.last_node = 0
        return cls.nodes[cls.last_node]

DistributeManager.register('get_node', callable=DistributeManager._get_node)

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
        
    id = config.get(manager_section, 'id')

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
                raise RuntimeError("Invalid node value. Node values should be given as <host>:<port>")
            index = value.index(delim)
            nodes.append((value[:index], int(value[index+1:])))
        else:
            done = True
    if not nodes:
        raise RuntimeErrors("No build nodes configured.")
   
    DistributeManager._set_nodes(nodes)
    print("Spawning a manager with id '{}'".format(id))
    print("================")
    print("Build nodes:")
    print("================")
    for node in nodes:
        print('{}:{}'.format(node[0], node[1]))
    print("================")
    manager = DistributeManager(r"\\.\pipe\{}".format(id), b"")
    server = manager.get_server()
    server.serve_forever()
