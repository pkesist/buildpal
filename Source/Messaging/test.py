import zmq

from server import MatchMakerWorker, Session
from matchmaker import MatchMaker
from multiprocessing import Process
from client import MatchMakerClient

class EchoSession(Session):
    def __init__(self, *args, **kwargs):
        Session.__init__(self, *args, **kwargs)
        self.counter = 0

    def process_msg(self):
        print("-*---------- PROCESS_MSG", id(self), self.counter)
        if self.counter == 0:
            print("adgadgadg")
            self.message = self.recv()
            print("adgadgadg12341243")
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
        MatchMakerWorker(zmq.Context(), self.__address, EchoSession).run()

class Broker(Process):
    def __init__(self, client_address, server_address):
        Process.__init__(self)
        self.__client_address = client_address
        self.__server_address = server_address

    def run(self):
        MatchMaker(zmq.Context(1), self.__client_address, self.__server_address).run()

if __name__ == '__main__':
    broker = Broker('tcp://*:5555', 'tcp://*:5556')
    worker = EchoWorker('tcp://localhost:5556')
    
    broker.start()
    worker.start()
    
    try:
        zmq_ctx = zmq.Context()
        client = MatchMakerClient(zmq_ctx, 'tcp://localhost:5555')
        client2 = MatchMakerClient(zmq_ctx, 'tcp://localhost:5555')
        client.send_pyobj('EINE KLEINE NACHTMUSIK')
        client.send_pyobj('WHATEVER')
        print("ERSTE")
        first_reply = client.recv_pyobj()
        print("ZWEITE")
        second_reply = client.recv_pyobj()
        assert first_reply == "I REMEMBERED!"
        assert second_reply == 'EINE KLEINE NACHTMUSIK'

        client2.send_pyobj('ZARZALO')
        client2.send_pyobj('WHATEVER')
        print("PRVI")
        first_reply2 = client2.recv_pyobj()
        print("DRUGI")
        second_reply2 = client2.recv_pyobj()
        assert first_reply2 == "I REMEMBERED!"
        assert second_reply2 == 'ZARZALO'
        print("adgklhdgkjadl")
    finally:
        broker.terminate()
        worker.terminate()