#! python3.3
import zmq
import collections

class MatchMaker:
    def __init__(self, zmq_ctx, client_address, server_address):
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

    def run(self):
        print("BROKER: starting")
        while True:
            socks = dict((self.poll_all if self.workers else self.poll_servers).poll())

            if socks.get(self.servers) == zmq.POLLIN:
                msg = self.servers.recv_multipart()
                print("BROKER: '{}' on server socket".format(msg))
                name = msg[0]
                if len(msg) == 2 and msg[1] == b'READY':
                    print("BROKER: SERVER {} REGISTERED!!!".format(name))
                    if name in self.workers:
                        self.servers.send_multipart([name, b'ONCE IS FINE'])
                    else:
                        self.workers.append(name)
                        self.servers.send_multipart([name, b'OK'])
                else:
                    self.clients.send_multipart(msg[1:])
            
            if socks.get(self.clients) == zmq.POLLIN:
                msg = self.clients.recv_multipart()
                print("BROKER: '{}' on client socket".format(msg))
                name = msg[0]
                
                if len(msg) == 2 and msg[1] == b'GIMME':
                    server = self.workers[0]
                    self.workers.rotate(1)
                    self.clients.send_multipart([name, server])
                    self.servers.send_multipart([server, name, b'CREATE_SESSION'])
                else:
                    assert len(msg) > 2
                    payload = [msg[1], msg[0]] + msg[2:]
                    print("BROKER: Sending '{}' to server socket.".format(payload))
                    self.servers.send_multipart(payload)

    
