import zmq
import pickle
import random

class Session:
    def __init__(self, recv, send):
        self.__recv = recv
        self.__send = send

    def process_msg(self):
        raise NotImplementedError()
    
    def send(self, msg):
        self.__send(msg)

    def send_pyobj(self, obj):
        self.send([pickle.dumps(obj)])
        
    def recv(self):
        return self.__recv()

    def recv_pyobj(self):
        return pickle.loads(self.recv()[0])

class MatchMakerWorker:
    def __init__(self, zmq_ctx, address, session_class):
        assert issubclass(session_class, Session)
        self.zmq_ctx = zmq_ctx
        self.broker = self.zmq_ctx.socket(zmq.DEALER)
        self.address = address
        self.session_class = session_class
        
        self.sessions = self.zmq_ctx.socket(zmq.ROUTER)
        self.sessions_addr = 'inproc://session_socket'
        self.sessions.bind(self.sessions_addr)
        
        self.poller = zmq.Poller()
        self.poller.register(self.broker, zmq.POLLIN)
        self.poller.register(self.sessions, zmq.POLLIN | zmq.POLLOUT)

        self.session_poller = zmq.Poller()
        self.client_id_to_session = {}

    def make_session():
        raise NotImplementedError()

    def run(self):
        print("WORKER: connecting to '{}'".format(self.address))
        self.broker.connect(self.address)
        print("WORKER: sending 'READY' to '{}'".format(self.address))
        self.broker.send(b'READY')
        print("WORKER: waiting for 'OK' from '{}'".format(self.address))
        assert self.broker.recv() == b'OK'
        print("WORKER: got 'OK' from '{}'".format(self.address))

        while True:
            sockets = dict(self.poller.poll())

            for sock, event in sockets.items():
                if event != zmq.POLLIN:
                    continue

                if sock is self.broker:
                    msg = self.broker.recv_multipart()
                    print("WORKER: Got '{}' from broker.".format(msg))
                    client = msg[0]
                    if msg[1] == b'CREATE_SESSION':
                        incoming = self.zmq_ctx.socket(zmq.DEALER)
                        incoming.setsockopt(zmq.IDENTITY, client)
                        incoming.connect(self.sessions_addr)
                    
                        class Recv:
                            def __init__(self, incoming):
                                self.__incoming = incoming
                            def __call__(self):
                                return self.__incoming.recv_multipart()

                        class Send:
                            def __init__(self, outgoing, client_id):
                                self.__outgoing = outgoing
                                self.__client_id = client_id

                            def __call__(self, msg):
                                return self.__outgoing.send_multipart([self.__client_id] + msg)

                        recv = Recv(incoming)
                        send = Send(self.broker, client)

                        session = self.session_class(recv, send)
                        self.client_id_to_session[client] = session
                        self.poller.register(incoming, zmq.POLLIN)
                    else:
                        session = self.client_id_to_session.get(client)
                        if session:
                            payload = [client] + msg[1:]
                            print("WORKER: Sending '{}' to session".format(payload))
                            self.sessions.send_multipart(payload)
                        else:
                            print("WORKER: Data for invalid session.")
                            print("Sessions")
                            for x in self.client_id_to_session:
                                print("Client '{}' - session '{}'".format(x, self.client_id_to_session[x]))
                            print("Requested client is '{}'".format(client))
                
                elif sock is self.sessions:
                    msg = self.sessions.recv_multipart()
                    print("WORKER: Got '{}' from sessions.".format(msg))
                    # Session socket has the same id as the client socket,
                    # so there is no need to do the translation here.
                    self.broker.send_multipart(msg)
                
                else:
                    client = sock.getsockopt(zmq.IDENTITY)
                    session = self.client_id_to_session[client]
                    close_session = session.process_msg()
                    if close_session:
                        self.poller.unregister(sock)
                        del self.client_id_to_session[client]
