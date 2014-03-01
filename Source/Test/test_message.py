import sys
sys.path.append('..')

from Common.message import msg_from_bytes, msg_to_bytes, MessageProtocol

def test_msg():
    data = list(b'asdf'*x for x in range(256))
    byte_data_gen, total_length = msg_to_bytes(data)
    recreated_data = list(msg_from_bytes(b''.join(byte_data_gen)))
    assert data == recreated_data

def test_protocol():
    class FakeTransport:
        def __init__(self, protocol):
            self.protocol = protocol

        def sendall(self, data):
            self.protocol.data_received(data)

    def fake_connect(protocol1, protocol2):
        protocol1.connection_made(FakeTransport(protocol2))
        protocol2.connection_made(FakeTransport(protocol1))

    class Processor:
        def __init__(self):
            self.msgs = []

        def process_msg(self, msg):
            self.msgs.append(msg)

        def get_msg(self):
            return self.msgs.pop(0)

    def test_transfer(protocol1, protocol2, msg):
        protocol1.send_msg(msg)
        assert all(x==y for x, y in zip(protocol2.message_processor.get_msg(),
            msg))

    processor1 = Processor()
    processor2 = Processor()

    protocol1 = MessageProtocol(processor1)
    protocol2 = MessageProtocol(processor2)

    fake_connect(protocol1, protocol2)

    test_transfer(protocol1, protocol2, [b'ASDF1', b'FSDA5'] * 1 )
    test_transfer(protocol1, protocol2, [b'ASDF2', b'FSDA4'] * 2 )
    test_transfer(protocol1, protocol2, [b'ASDF3', b'FSDA3'] * 4 )
    test_transfer(protocol1, protocol2, [b'ASDF4', b'FSDA2'] * 8 )
    test_transfer(protocol1, protocol2, [b'ASDF5', b'FSDA1'] * 16)

    test_transfer(protocol2, protocol1, [b'ASDF1', b'FSDA5'] * 1 )
    test_transfer(protocol2, protocol1, [b'ASDF2', b'FSDA4'] * 2 )
    test_transfer(protocol2, protocol1, [b'ASDF3', b'FSDA3'] * 4 )
    test_transfer(protocol2, protocol1, [b'ASDF4', b'FSDA2'] * 8 )
    test_transfer(protocol2, protocol1, [b'ASDF5', b'FSDA1'] * 16)


