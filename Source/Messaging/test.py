import zmq

from server import ServerWorker, ServerSession
from broker import Broker
from multiprocessing import Process
from client import Client

class EchoSession(ServerSession):
    def __init__(self, *args, **kwargs):
        ServerSession.__init__(self, *args, **kwargs)
        self.counter = 0

    def process_msg(self):
        if self.counter == 0:
            self.message = self.recv()
            self.send_pyobj("I REMEMBERED!")
            self.counter += 1
            return False
        if self.counter == 1:
            self.recv()
            self.send(self.message)
        return True

class EchoWorker(Process):
    def __init__(self, address):
        Process.__init__(self)
        self.__address = address

    def run(self):
        ServerWorker(zmq.Context(), self.__address, EchoSession).run()

class BrokerProcess(Process):
    def __init__(self, client_address, server_address):
        Process.__init__(self)
        self.__client_address = client_address
        self.__server_address = server_address

    def run(self):
        Broker(zmq.Context(), self.__client_address, self.__server_address).run()

if __name__ == '__main__':
    broker = BrokerProcess('tcp://*:5555', 'tcp://*:5556')
    worker = EchoWorker('tcp://localhost:5556')
    
    broker.start()
    worker.start()
    
    try:
        zmq_ctx = zmq.Context()
        client = Client(zmq_ctx, 'tcp://localhost:5555')
        client2 = Client(zmq_ctx, 'tcp://localhost:5555')
        client.send_pyobj('EINE KLEINE NACHTMUSIK')
        client2.send_pyobj('ZARZALO')
        client.send_pyobj('WHATEVER')
        client2.send_pyobj('WHATEVER')

        first_reply = client.recv_pyobj()
        first_reply2 = client2.recv_pyobj()
        second_reply = client.recv_pyobj()
        second_reply2 = client2.recv_pyobj()

        assert first_reply == "I REMEMBERED!"
        assert second_reply == 'EINE KLEINE NACHTMUSIK'
        assert first_reply2 == "I REMEMBERED!"
        assert second_reply2 == 'ZARZALO'
    finally:
        broker.terminate()
        worker.terminate()