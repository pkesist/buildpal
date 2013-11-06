import zmq
import pickle

class ServerSession:
    def created(self):
        return True

    def attached(self, attacher_id):
        pass
    
    def process_msg(self, msg):
        raise NotImplementedError()

    def process_attached_msg(self, socket, msg):
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

    def __create_session(self):
        socket = self.zmq_ctx.socket(zmq.DEALER)
        socket.connect(self.sessions_addr)

        session = self.session_factory()
        assert issubclass(type(session), ServerSession)
        session.socket = socket
        session.attached_sockets = set()
        session.recv = session.socket.recv
        session.send = session.socket.send
        session.recv_multipart = session.socket.recv_multipart
        session.send_multipart = session.socket.send_multipart

        self.socket_to_session[socket] = session
        self.poller.register(session.socket, zmq.POLLIN)
        return session

    def __attach_to_session(self, session):
        socket = self.zmq_ctx.socket(zmq.DEALER)
        socket.connect(self.sessions_addr)
        session.attached_sockets.add(socket)
        self.socket_to_session[socket] = session
        self.poller.register(socket, zmq.POLLIN)
        return socket

    def __detach_from_session(self, session, socket):
        assert socket in session.attached_sockets
        self.poller.unregister(socket)
        session.attached_sockets.remove(socket)
        # Throws resource temporarily unavailable.
        #session.socket.disconnect(self.sessions_addr)

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
                assert event == zmq.POLLIN

                if sock is self.broker:
                    msg = self.broker.recv_multipart(flags=zmq.NOBLOCK)
                    if msg[0] == b'CREATE_SESSION':
                        session = self.__create_session()
                        session.socket.send_multipart([b'SESSION_CREATED'], copy=False)
                        session.created()
                    elif msg[0] == b'ATTACH_TO_SESSION':
                        session_id = msg[1]
                        attacher_id = msg[2]
                        self.sessions.send_multipart([session_id, b'ATTACH', attacher_id])
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
                    msg = sock.recv_multipart()
                    session = self.socket_to_session.get(sock)
                    if msg[0] == b'ATTACH':
                        assert session
                        attacher_id = msg[1]
                        socket = self.__attach_to_session(session)
                        session.attached(attacher_id)
                        socket.send_multipart([b'SESSION_ATTACHED', attacher_id])
                    else:
                        if not session:
                            continue
                        if sock is session.socket and session.process_msg(msg):
                            self.__destroy_session(session)
                        elif sock in session.attached_sockets:
                            detach, destroy_session = session.process_attached_msg(sock, msg)
                            # destroy_session ==> detach
                            assert not destroy_session or detach
                            if detach:
                                self.__detach_from_session(session, sock)
                            if destroy_session:
                                self.__destroy_session(session)


