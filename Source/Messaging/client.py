import zmq
import pickle
import random

class MatchMakerClient:
    def __init__(self, zmq_ctx, address):
        self.socket = zmq_ctx.socket(zmq.DEALER)
        identity = "{:x}-{:x}".format(
            random.randrange(0, 0x10000),
            random.randrange(0, 0x10000)).encode()
        self.socket.setsockopt(zmq.IDENTITY, identity)
        self.socket.connect(address)
        self.socket.send(b'GIMME')
        self.server_id = self.socket.recv()

    def send(self, msg):
        self.socket.send_multipart([self.server_id] + msg)

    def recv(self):
        return self.socket.recv_multipart()

    def send_pyobj(self, obj):
        self.send([pickle.dumps(obj)])

    def recv_pyobj(self):
        return pickle.loads(self.recv()[0])

