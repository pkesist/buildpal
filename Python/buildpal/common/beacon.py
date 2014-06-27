import socket
import struct

from threading import Thread, Condition

def _get_multicast_socket(multicast_address):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    addrinfo = socket.getaddrinfo('', 0, family=socket.AF_INET)
    addrinfo.extend(socket.getaddrinfo('localhost', 0, family=socket.AF_INET))
    for _, _, _, _, (address, port) in addrinfo:
        mreq = struct.pack('=4s4s', socket.inet_aton(multicast_address), socket.inet_aton(address))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

class Beacon:
    discover_string = b'BP_MGR_DISCOVER'

    def __init__(self, slots, server_port):
        self.response = b'BP_MGR_SERVER' + struct.pack('!2H32p', server_port, slots, socket.getfqdn().encode())
        self.running_cond = Condition()
        self.running = False

    def start(self, multicast_address, multicast_port):
        """
        Starts beacon. Will block until the worker thread is actually started.
        """
        if self.running:
            raise Exception("Tried to start beacon twice.")
        self.socket = _get_multicast_socket(multicast_address)
        self.thread = Thread(target=self.__run_beacon, args=(multicast_port,))
        self.thread.start()
        with self.running_cond:
            while not self.running:
                self.running_cond.wait()

    def stop(self):
        if not self.running:
            raise Exception("Tried to stop beacon which was not started.")
        self.running = False
        self.socket.close()
        self.thread.join()

    def __run_beacon(self, multicast_port):
        self.socket.bind(('', multicast_port))
        with self.running_cond:
            self.running = True
            self.running_cond.notify_all()
        while self.running:
            try:
                data, (addr, port) = self.socket.recvfrom(64)
                if data[:len(self.discover_string)] == self.discover_string:
                    self.socket.sendto(self.response, (addr, port))
            except OSError:
                pass

def _parse_response(response, address):
    prefix = b'BP_MGR_SERVER'
    prefix_len = len(prefix)
    if response[:prefix_len] != prefix:
        return None
    if len(response) == prefix_len + 2 + 2 + 32:
        port, job_slots, hostname = struct.unpack('!2H32p', response[prefix_len:])
        return {
            'address' : address,
            'port' : port,
            'hostname' : hostname.decode().strip(),
            'job_slots' : job_slots}
    if len(response) == prefix_len + 2 + 2:
        port, job_slots = struct.unpack('!2H', response[prefix_len:])
        return {
            'address' : address,
            'port' : port,
            'hostname' : "<{}>".format(address),
            'job_slots' : job_slots}

def get_nodes_from_beacons(multicast_address, multicast_port):
    sock = _get_multicast_socket(multicast_address)
    sock.setblocking(False)
    sock.bind(('', 0))
    nodes = {}

    with sock:
        sock.sendto(b'BP_MGR_DISCOVER', (multicast_address, multicast_port))
        while True:
            sock.settimeout(0.1)
            try:
                data, (address, port) = sock.recvfrom(256)
            except socket.timeout:
                break
            if (address, port) not in nodes:
                result = _parse_response(data, address)
                if result is not None:
                    nodes[(address, port)] = result
    return list(nodes.values())
