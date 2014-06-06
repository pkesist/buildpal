import os
import sys
import subprocess

from .gui import BPManagerApp
from .runner import ManagerRunner
from .node_info import NodeInfo

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

def main(opts, terminator=None):
    config = None

    if opts.debug:
        import logging
        logging.basicConfig(fileName='manager_debug.log', level=logging.DEBUG)

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

    if opts.ui == 'gui':
        app = BPManagerApp(node_info_getter, port)
        app.title('BuildPal Manager')

        def run(runner):
            try:
                runner.run(node_info_getter, update_ui=app.post_event)
            except Exception as e:
                app.post_event(GUIEvent.exception_in_run, e)

        def wait():
            app.mainloop()

        manager_runner = ManagerRunner(port, 0)
        thread = Thread(target=run, args=(manager_runner,))
        thread.start()
        try:
            wait()
        finally:
            manager_runner.stop()
            thread.join()

    else:
        try:
            manager_runner = ManagerRunner(port, 0)
            if terminator:
                terminator.initialize(manager_runner.stop)
            manager_runner.run(node_info_getter, silent=opts.ui == 'none')
        except KeyboardInterrupt:
            pass
        #def run(runner):
        #    runner.run(node_info_getter, silent=opts.ui == 'none')
        #
        #def wait():
        #    try:
        #        while not terminator or not terminator.should_stop():
        #            sleep(1)
        #    except KeyboardInterrupt:
        #        pass


if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    result = main(sys.argv[1:])
    if result:
        sys.exit(result)
