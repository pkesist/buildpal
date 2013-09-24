import zmq
import pickle

class ServerSession:
    def created(self):
        return True

    def process_msg(self):
        raise NotImplementedError()
    
    def send_pyobj(self, obj):
        self.send(pickle.dumps(obj))

    def recv_pyobj(self):
        return pickle.loads(self.recv())

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

        self.socket_to_session = {}


    def connect_broker(self, address):
        self.broker.connect(address)

    def bind_broker(self, address):
        self.broker.bind(address)

    def connect_control(self, address):
        self.control.connect(address)

    def bind_control(self, address):
        self.control.bind(address)

    def __create_session(self, client_id):
        socket = self.zmq_ctx.socket(zmq.DEALER)
        socket.connect(self.sessions_addr)

        session = self.session_factory()
        assert issubclass(type(session), ServerSession)
        session.socket = socket
        session.recv = session.socket.recv
        session.send = session.socket.send
        session.recv_multipart = session.socket.recv_multipart
        session.send_multipart = session.socket.send_multipart

        self.socket_to_session[socket] = session
        self.poller.register(session.socket, zmq.POLLIN)
        return session

    def __destroy_session(self, session):
        del self.socket_to_session[session.socket]
        self.poller.unregister(session.socket)
        session.socket.send(b'SESSION_DESTROYED')
        # Throws resource temporarily unavailable.
        #session.socket.disconnect(self.sessions_addr)

    def run(self):
        self.broker.send(b'READY')
        assert self.broker.recv() == b'OK'

        while True:
            sockets = dict(self.poller.poll())

            for sock, event in sockets.items():
                if event != zmq.POLLIN:
                    continue

                if sock is self.broker:
                    msg = self.broker.recv_multipart(flags=zmq.NOBLOCK)
                    # FIXME: client_id should be removed totally if
                    # broker is smarter.
                    client_id = msg[0]
                    if msg[1] == b'CREATE_SESSION':
                        session = self.__create_session(client_id)
                        session.socket.send_multipart([b'SESSION_CREATED', client_id], copy=False)
                        session.created()
                    else:
                        self.sessions.send_multipart(msg, copy=False)
                
                elif sock is self.sessions:
                    msg = self.sessions.recv_multipart(flags=zmq.NOBLOCK)
                    self.broker.send_multipart(msg, copy=False)
                
                elif sock is self.control:
                    msg = self.control.recv_multipart()
                    if msg[0] == b'SHUTDOWN':
                        return
                else:
                    # Must be a session socket.
                    session = self.socket_to_session.get(sock)
                    if session and session.process_msg():
                        self.__destroy_session(session)
