#! python3.3
import zmq
import collections

class Broker:
    def __init__(self, zmq_ctx):
        self.clients = zmq_ctx.socket(zmq.ROUTER)
        self.servers = zmq_ctx.socket(zmq.ROUTER)

        self.poll_servers = zmq.Poller()
        self.poll_servers.register(self.servers, zmq.POLLIN)

        self.poll_all = zmq.Poller()
        self.poll_all.register(self.clients, zmq.POLLIN)
        self.poll_all.register(self.servers, zmq.POLLIN)

        self.workers = collections.deque()

        self.control = zmq_ctx.socket(zmq.SUB)
        self.control.setsockopt(zmq.SUBSCRIBE, b'')
        self.poll_servers.register(self.control, zmq.POLLIN)
        self.poll_all.register(self.control, zmq.POLLIN)

    def bind_clients(self, address):
        self.clients.bind(address)

    def bind_servers(self, address):
        self.servers.bind(address)

    def connect_servers(self, address):
        self.servers.connect(address)

    def connect_control(self, address):
        self.control.connect(address)

    def bind_control(self, address):
        self.control.bind(address)

    def run(self):
        while True:
            socks = dict((self.poll_all if self.workers else self.poll_servers).poll())

            if socks.get(self.servers) == zmq.POLLIN:
                msg = self.servers.recv_multipart()
                name = msg[0]
                if len(msg) == 2 and msg[1] == b'READY':
                    if name in self.workers:
                        self.servers.send_multipart([name, b'ONCE IS FINE'])
                    else:
                        self.workers.append(name)
                        self.servers.send_multipart([name, b'OK'])
                else:
                    self.clients.send_multipart(msg[1:])
            
            if socks.get(self.clients) == zmq.POLLIN:
                msg = self.clients.recv_multipart()
                name = msg[0]
                
                if len(msg) == 2 and msg[1] == b'GIMME':
                    server = self.workers[0]
                    self.workers.rotate(1)
                    self.clients.send_multipart([name, server])
                    self.servers.send_multipart([server, name, b'CREATE_SESSION'])
                else:
                    assert len(msg) > 2
                    payload = [msg[1], msg[0]] + msg[2:]
                    self.servers.send_multipart(payload)

            if socks.get(self.control) == zmq.POLLIN:
                msg = self.control.recv_multipart()
                if msg[0] == b'SHUTDOWN':
                    return

    
