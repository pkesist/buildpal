import os
import sys
import subprocess

from .gui import BPManagerApp
from .manager_runner import ManagerRunner
from .node_info import NodeInfo

def run_gui(node_info_getter, port):
    app = BPManagerApp(node_info_getter, port)
    app.title('BuildPal Manager')
    app.mainloop()

import argparse
import configparser

from threading import Thread
from time import sleep

class FixedNodeList:
    def __init__(self, config, profile):
        nodes = FixedNodeList.get_nodes_from_ini_file(config, profile)
        self.node_info = [NodeInfo(node) for node in nodes]

    def __call__(self):
        return self.node_info

    @staticmethod
    def get_nodes_from_ini_file(config, profile):
        if not profile in config:
            raise Exception("ERROR: No '{}' section in '{}'.".format(profile, opts.ini_file))

        nodes = []
        section = config[profile]
        done = False
        while not done:
            option = "node[{}]".format(len(nodes))
            if option in section:
                value = section[option]
                delim = ':'
                if not delim in value:
                    raise RuntimeError("Invalid node value. Node values should be given as <host>:<port>[:<job_slots>]")
                port_index = value.index(delim)
                try:
                    job_slots_index = value.index(':', port_index + 1)
                    server_port = int(value[port_index + 1 : job_slots_index])
                    job_slots = int(value[job_slots_index + 1 : ])
                except ValueError:
                    server_port = int(value[port_index + 1:])
                    job_slots = None
                nodes.append({
                    'address' : value[:port_index],
                    'hostname' : '<{}>'.format(value[:port_index]),
                    'port' : server_port,
                    'job_slots' : job_slots })
            else:
                done = True
        return nodes

class NodeDetector:
    def __init__(self):
        self.all_node_infos = {}

    def _get_node_info(self, node):
        node_id = '{}:{}'.format(node['hostname'], node['port'])
        return self.all_node_infos.setdefault(node_id, NodeInfo(node))

    def __call__(self):
        nodes = NodeDetector.get_nodes_from_beacon()
        return [self._get_node_info(node) for node in nodes]

    @staticmethod
    def get_nodes_from_beacon():
        import socket
        import select
        import struct
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        multicast_group = '239.192.29.71'
        multicast_port = 51134
        # when sending multicast, it is not enough to add membership to
        # socket.INADDR_ANY. Windows will send multicast message through
        # only one interface - loopback. We need to enumerate interfaces
        # and add membership to each one.
        addrinfo = socket.getaddrinfo('', 0, family=socket.AF_INET)
        addrinfo.extend(socket.getaddrinfo('localhost', 0, family=socket.AF_INET))
        for _, _, _, _, (address, port) in addrinfo:
            mreq = struct.pack('=4s4s', socket.inet_aton(multicast_group), socket.inet_aton(address))
            udp.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.setblocking(False)
        udp.bind(('', 0))
        udp.sendto(b'BP_MGR_DISCOVER', (multicast_group, multicast_port))
        nodes = []
        while True:
            udp.settimeout(0.2)
            try:
                data, (address, port) = udp.recvfrom(256)
            except socket.timeout:
                break
            prefix = b'BP_MGR_SERVER'
            prefix_len = len(prefix)
            if data[:prefix_len] != prefix:
                continue
            if len(data) == prefix_len + 2 + 2 + 32:
                port, job_slots, hostname = struct.unpack('!2H32p', data[prefix_len:])
                nodes.append({
                    'address' : address,
                    'port' : port,
                    'hostname' : hostname.decode().strip(),
                    'job_slots' : job_slots})
            elif len(data) == prefix_len + 2 + 2:
                port, job_slots = struct.unpack('!2H', data[prefix_len:])
                nodes.append({
                    'address' : address,
                    'port' : port,
                    'hostname' : "<{}>".format(address),
                    'job_slots' : job_slots})

        udp.close()
        return nodes

def get_config(ini_file):
    config = configparser.SafeConfigParser(strict=False)
    if not config.read(ini_file):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(ini_file))
    return config

def main(argv, terminator=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--ui', choices=['gui', 'console', 'none'],
        default='gui', help='Select user interface')
    parser.add_argument('--port', dest='port', type=str, default=None,
        help='Port on which manager should run.')
    parser.add_argument('--ini', dest='ini_file', type=str, default=None,
        help='Specify .ini file.')
    parser.add_argument('--debug', '-d', action='store_true', dest='debug',
        default=False, help='Enable debug logging.')
    parser.add_argument('--profile', type=str, default=None,
        help='Profile to use. Must be present in the .ini file.')
    parser.add_argument('--connect', dest='connect', type=str, default=None,
        help='Manager port to connect to.')
    parser.add_argument('--run', nargs=argparse.REMAINDER,
        help='Trailing arguments specify command to run.')

    opts = parser.parse_args(argv)

    config = None

    if opts.debug:
        import logging
        logging.basicConfig(fileName='manager_debug.log', level=logging.DEBUG)

    if opts.connect is None:
        if opts.port is None:
            port = os.environ.get('BP_MANAGER_PORT')
            if port is None:
                print("Port name not specified, using default port ('default').", file=sys.stdout)
                port = 'default'
        else:
            port = opts.port

        if opts.profile is None:
            node_info_getter = NodeDetector()
        else:
            if not opts.ini_file:
                print("ERROR: Profile specified, but .ini file is not.", file=sys.stderr)
                return -1
            node_info_getter = FixedNodeList(get_config(opts.ini_file), opts.profile)
    else:
        port = opts.connect

    class OverrideCreateProcess:
        from buildpal_manager.compilers.msvc import setup_hooks
        create_process = setup_hooks(port)

        def __enter__(self):
            self.save = subprocess._winapi.CreateProcess
            subprocess._winapi.CreateProcess = self.create_process

        def __exit__(self, exc_type, exc_value, traceback):
            subprocess._winapi.CreateProcess = self.save
            self.save = None

    proc = None
    if opts.run:
        with OverrideCreateProcess():
            proc = subprocess.Popen(['cmd.exe', '/S', '/K'] + opts.run,
                creationflags=subprocess.CREATE_NEW_CONSOLE |
                    subprocess.CREATE_NEW_PROCESS_GROUP)

    if opts.connect is None:
        if opts.ui == 'gui':
            run_gui(node_info_getter, port)
        else:
            silent = opts.ui == 'none'
            manager_runner = ManagerRunner(port, 0)
            def run():
                manager_runner.run(node_info_getter, silent=silent)
            thread = Thread(target=run)
            thread.start()
            try:
                while not terminator or not terminator.should_stop():
                    sleep(1)
            finally:
                if not silent:
                    print("Shutting down.")
                manager_runner.stop()
                thread.join()
        if proc:
            proc.terminate()
            proc.wait()

if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    result = main(sys.argv[1:])
    if result:
        sys.exit(result)
