import zmq
import pickle
import random

class ServerSession:
    def created(self):
        return True

    def process_msg(self):
        raise NotImplementedError()
    
    def setup_communication(self, recv, send):
        self.recv = recv
        self.send = send

    def send_pyobj(self, obj):
        self.send([pickle.dumps(obj)])

    def recv_pyobj(self):
        return pickle.loads(self.recv()[0])

class ServerWorker:
    def __init__(self, zmq_ctx, session_factory):
        self.zmq_ctx = zmq_ctx
        self.broker = self.zmq_ctx.socket(zmq.DEALER)
        self.session_factory = session_factory
        
        self.sessions = self.zmq_ctx.socket(zmq.ROUTER)
        self.sessions_addr = 'inproc://sessions_socket'
        self.sessions.bind(self.sessions_addr)
        
        self.control = zmq_ctx.socket(zmq.SUB)
        self.control.setsockopt(zmq.SUBSCRIBE, b'')

        self.poller = zmq.Poller()
        self.poller.register(self.broker, zmq.POLLIN)
        self.poller.register(self.sessions, zmq.POLLIN)
        self.poller.register(self.control, zmq.POLLIN)

        self.client_id_to_session = {}


    def connect_broker(self, address):
        self.broker.connect(address)

    def bind_broker(self, address):
        self.broker.bind(address)

    def connect_control(self, address):
        self.control.connect(address)

    def bind_control(self, address):
        self.control.bind(address)

    def __create_session(self, client_id):
        incoming = self.zmq_ctx.socket(zmq.DEALER)
        # Make the session socket have the same id as the client
        # socket.
        incoming.setsockopt(zmq.IDENTITY, client_id)
        incoming.connect(self.sessions_addr)
                    
        class Recv:
            def __init__(self, poller, incoming):
                self.__poller = poller
                self.__poller.register(incoming, zmq.POLLIN)
                self.__incoming = incoming

            def __del__(self):
                self.__poller.unregister(self.__incoming)

            def __call__(self):
                return self.__incoming.recv_multipart()

        class Send:
            def __init__(self, outgoing, client_id):
                self.__outgoing = outgoing
                self.__client_id = client_id

            def __call__(self, msg):
                return self.__outgoing.send_multipart([self.__client_id] + msg)

        recv = Recv(self.poller, incoming)
        send = Send(self.broker, client_id)

        session = self.session_factory()
        assert issubclass(type(session), ServerSession)
        session.setup_communication(recv, send)

        if session.created():
            self.client_id_to_session[client_id] = session
            return session
        return None

    def __get_session(self, client_id):
        return self.client_id_to_session.get(client_id)

    def __destroy_session(self, client_id):
        del self.client_id_to_session[client_id]

    def run(self):
        self.broker.send(b'READY')
        assert self.broker.recv() == b'OK'

        while True:
            sockets = dict(self.poller.poll())

            for sock, event in sockets.items():
                if event != zmq.POLLIN:
                    continue

                if sock is self.broker:
                    msg = self.broker.recv_multipart()
                    if msg[1] == b'CREATE_SESSION':
                        client_id = msg[0]
                        session = self.__create_session(client_id)
                    else:
                        # Session socket has the same id as the client socket,
                        # so there is no need to do the translation here.
                        self.sessions.send_multipart(msg)
                
                elif sock is self.sessions:
                    msg = self.sessions.recv_multipart()
                    # Session socket has the same id as the client socket,
                    # so there is no need to do the translation here.
                    self.broker.send_multipart(msg)
                
                elif sock is self.control:
                    msg = self.control.recv_multipart()
                    if msg[0] == b'SHUTDOWN':
                        return
                else:
                    # Must be a session socket.
                    client_id = sock.getsockopt(zmq.IDENTITY)
                    session = self.__get_session(client_id)
                    if session:
                        close_session = session.process_msg()
                        if close_session:
                            self.__destroy_session(client_id)
