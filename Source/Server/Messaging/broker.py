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
        workers = collections.deque()
        server_from_client = {}
        client_from_server = {}
        clients_waiting_for_session = []

        while True:
            socks = dict((self.poll_all if workers else self.poll_servers).poll())

            if socks.get(self.servers) == zmq.POLLIN:
                msg = self.servers.recv_multipart(flags=zmq.NOBLOCK)
                name = msg[0]
                if len(msg) == 2 and msg[1] == b'READY':
                    assert name not in workers
                    workers.append(name)
                    self.servers.send_multipart([name, b'OK'])

                elif len(msg) == 3 and msg[2] == b'SESSION_CREATED':
                    server_id = msg[0]
                    session_id = msg[1]
                    client_id = clients_waiting_for_session[0]
                    del clients_waiting_for_session[0]
                    server_from_client[client_id] = (server_id, session_id)
                    client_from_server[(server_id, session_id)] = client_id
                    self.clients.send_multipart([client_id, b'SESSION_CREATED'])

                elif len(msg) == 4 and msg[2] == b'SESSION_ATTACHED':
                    server_id = msg[0]
                    session_id = msg[1]
                    attacher_id = msg[3]
                    server_from_client[attacher_id] = (server_id, session_id)
                    client_from_server[(server_id, session_id)] = attacher_id
                    self.clients.send_multipart([attacher_id, b'SESSION_ATTACHED'])

                elif len(msg) == 3 and msg[2] == b'SESSION_DESTROYED':
                    server_id = msg[0]
                    session_id = msg[1]
                    client_id = client_from_server[(server_id, session_id)]
                    self.clients.send_multipart([client_id, b'SESSION_DESTROYED'])
                    del client_from_server[(server_id, session_id)]
                    del server_from_client[client_id]
                else:
                    server_id = msg[0]
                    session_id = msg[1]
                    client_id = client_from_server[(server_id, session_id)]
                    self.clients.send_multipart([client_id] + msg[2:], copy=False)

            if socks.get(self.clients) == zmq.POLLIN:
                msg = self.clients.recv_multipart(flags=zmq.NOBLOCK)
                
                if len(msg) == 2 and msg[1] == b'CREATE_SESSION':
                    client_id = msg[0]
                    workers.rotate(1)
                    server_id = workers[0]
                    clients_waiting_for_session.append(client_id)
                    self.servers.send_multipart([server_id, b'CREATE_SESSION'], copy=False)
                elif len(msg) == 3 and msg[1] == b'ATTACH_TO_SESSION':
                    attacher_id = msg[0]
                    client_id = msg[2]
                    server_id, session_id = server_from_client.get(client_id)
                    self.servers.send_multipart([server_id, b'ATTACH_TO_SESSION', session_id, attacher_id], copy=False)
                else:
                    client_id = msg[0]
                    server_id, session_id = server_from_client.get(client_id)
                    self.servers.send_multipart([server_id, session_id] + msg[1:], copy=False)

            if socks.get(self.control) == zmq.POLLIN:
                msg = self.control.recv_multipart()
                if msg[0] == b'SHUTDOWN':
                    return

    
