import zmq
import pickle
import random

class Client:
    def __init__(self, zmq_ctx):
        self.socket = zmq_ctx.socket(zmq.DEALER)
        identity = "{:x}-{:x}".format(
            random.randrange(0, 0x10000),
            random.randrange(0, 0x10000)).encode()
        self.socket.setsockopt(zmq.IDENTITY, identity)
        self.send = self.socket.send
        self.recv = self.socket.recv
        self.send_multipart = self.socket.send_multipart
        self.recv_multipart = self.socket.recv_multipart
        self.send_pyobj = self.socket.send_pyobj
        self.recv_pyobj = self.socket.recv_pyobj

    def connect(self, address):
        self.socket.connect(address)
        self.socket.send(b'CREATE_SESSION')
        assert self.socket.recv() == b'SESSION_CREATED'
