#! python3.3
from Manager import TaskProcessor, run_gui, Timer

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
    addrinfo = []
    addrinfo.extend((info for info in socket.getaddrinfo('', 0)))
    addrinfo.extend((info for info in socket.getaddrinfo('localhost', 0)))
    for x, y, z, (address, *port) in (x[1:] for x in addrinfo if x[0] == socket.AF_INET):
        mreq = struct.pack('=4s4s', socket.inet_aton(multicast_group), socket.inet_aton(address))
        udp.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.setblocking(False)
    udp.bind(('', 0))
    udp.sendto(b'DB_MGR_DISCOVER', (multicast_group, multicast_port))
    nodes = []
    while True:
        udp.settimeout(0.2)
        try:
            data, (address, port) = udp.recvfrom(256)
        except socket.timeout:
            break
        prefix = b'DB_MGR_SERVER'
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

    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    if opts.ui == 'gui':
        run_gui(nodes, port)
    else:
        try:
            ui_data = type('UIData', (), {})()
            TaskProcessor(nodes, port, 0, ui_data).run()
        except KeyboardInterrupt:
            print("Shutting down.")
