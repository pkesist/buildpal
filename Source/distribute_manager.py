#! python3.3
from Manager import TaskProcessor
from Manager import run_gui
from Manager import NodeInfo

import argparse
import configparser
import os
import sys

default_script = 'distribute_manager.ini'

def get_nodes_from_ini_file(config):
    if not opts.profile in config:
        raise Exception("ERROR: No '{}' section in '{}'.".format(opts.profile, opts.ini_file))

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
                server_port = int(value[port_index + 1:])
                max_tasks = None
            nodes.append({
                'address' : 'tcp://{}:{}'.format(value[:port_index], server_port),
                'max_tasks' : max_tasks })
        else:
            done = True
    return nodes

def get_nodes_from_beacon():
    import socket
    import select
    import struct
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp.setblocking(False)
    udp.sendto(b'DB_MGR_DISCOVER', ("<broadcast>", 51134))
    nodes = []
    r, w, e = select.select([udp], [], [], 0.1)
    while True:
        try:
            data, (address, port) = udp.recvfrom(256)
        except BlockingIOError:
            break
        prefix = b'DB_MGR_SERVER'
        prefix_len = len(prefix)
        if len(data) == prefix_len + 2 + 2 and data[:prefix_len] == prefix:
            port, max_tasks = struct.unpack('!2h', data[prefix_len:prefix_len+4])
            nodes.append({
                'address' : 'tcp://{}:{}'.format(address, port),
                'max_tasks' : max_tasks})
    return nodes

def get_config(ini_file):
    config = configparser.SafeConfigParser(strict=False)
    if not config.read(ini_file):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(ini_file))
    return config

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui', choices=['gui', 'console'], default='gui', help='Select user interface')
    parser.add_argument('--use-beacon', action='store_true', help='Autodetect LAN servers')
    parser.add_argument('--port', dest='port', type=int, default=None, help='TCP Port number on which manager should run.')
    parser.add_argument('--ini', dest='ini_file', type=str, default='distribute_manager.ini', help='Specify .ini file.')
    parser.add_argument('profile', nargs='?', type=str, default='Default Profile', help='Profile to use. Must be present in the .ini file.')
    
    opts = parser.parse_args()

    config = None

    if opts.port is None:
        config = get_config(opts.ini_file)
        port = config.get('Manager', 'port')

    if opts.use_beacon:
        nodes = get_nodes_from_beacon()
    else:
        if not config:
            config = get_config(opts.ini_file)
        nodes = get_nodes_from_ini_file(config)

    if not nodes:
        raise RuntimeError("No build nodes configured.")

    node_info = [NodeInfo(nodes[x], x) for x in range(len(nodes))]

    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    if opts.ui == 'gui':
        run_gui(node_info, port)
    else:
        try:
            TaskProcessor(node_info, port).run()
        except KeyboardInterrupt:
            print("Shutting down.")
