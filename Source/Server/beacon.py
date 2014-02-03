import threading
import socket
import struct

class Beacon:
    discover_string = b'DB_MGR_DISCOVER'

    def __init__(self, slots, server_port):
        self.response = b'DB_MGR_SERVER' + struct.pack('!2H', server_port, slots)
        self.running = False

    def start(self, multicast_address, multicast_port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        if self.running:
            raise Exception("Tried to start beacon twice.")
        self.thread = threading.Thread(target=self.__run_beacon, args=(multicast_address, multicast_port,))
        self.thread.start()
        self.running = True

    def stop(self):
        if not self.running:
            raise Exception("Tried to stop beacon which was not started.")
        self.socket.close()
        self.running = False
        self.thread.join()

    def __run_beacon(self, multicast_address, multicast_port):
        mreq = struct.pack('=4sL', socket.inet_aton(multicast_address), socket.INADDR_ANY)
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.socket.bind(('', multicast_port))
        while self.running:
            try:
                data, (addr, port) = self.socket.recvfrom(64)
                if data[:len(self.discover_string)] == self.discover_string:
                    self.socket.sendto(self.response, (addr, port))
            except OSError:
                pass
