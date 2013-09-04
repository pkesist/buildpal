import zmq
import pickle

class Client:
    def __init__(self, zmq_ctx):
        self.socket = zmq_ctx.socket(zmq.DEALER)
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
