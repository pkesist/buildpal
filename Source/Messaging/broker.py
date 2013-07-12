#! python3.3
import zmq
import collections

class Broker:
    def __init__(self, zmq_ctx, client_address, server_address, control_address=None):
        self.clients = zmq_ctx.socket(zmq.ROUTER)
        self.servers = zmq_ctx.socket(zmq.ROUTER)
        self.clients.bind(client_address)
        self.servers.bind(server_address)

        self.poll_servers = zmq.Poller()
        self.poll_servers.register(self.servers, zmq.POLLIN)

        self.poll_all = zmq.Poller()
        self.poll_all.register(self.clients, zmq.POLLIN)
        self.poll_all.register(self.servers, zmq.POLLIN)

        self.workers = collections.deque()

        if control_address:
            self.control = zmq_ctx.socket(zmq.SUB)
            self.control.connect(control_address)
            self.control.setsockopt(zmq.SUBSCRIBE, b'')
            self.poll_servers.register(self.control, zmq.POLLIN)
            self.poll_all.register(self.control, zmq.POLLIN)
        else:
            self.control = None

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

    
