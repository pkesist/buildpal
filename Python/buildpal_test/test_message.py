import sys
import pytest

sys.path.append('..')

from buildpal_common.message import msg_from_bytes, msg_to_bytes, MessageProtocol

def test_msg():
    data = list(b'asdf' * x for x in range(256))
    byte_data_gen = msg_to_bytes(data)
    total_len = next(byte_data_gen)
    mv = memoryview(b''.join(byte_data_gen))
    recreated_data = list(msg_from_bytes(mv))
    assert data == recreated_data

def test_memoryview_wrapper():
    data = list(b'asdf' * x for x in range(256))
    byte_data_gen = msg_to_bytes(data)
    total_len = next(byte_data_gen)
    bytes = b''.join(byte_data_gen)
    mv = memoryview(bytes)
    assert sys.getrefcount(bytes) == 1 + 1 + 1
    assert sys.getrefcount(mv) == 1 + 1
    recreated_data = list(msg_from_bytes(mv))
    assert sys.getrefcount(bytes) == 1 + 1 + 1
    del mv
    del recreated_data
    assert sys.getrefcount(bytes) == 1 + 1

def test_error_when_storing_msgs():
    class Protocol(MessageProtocol):
        def process_msg(self, msg):
            self.msg = msg

    class Protocol2(MessageProtocol):
        def process_msg(self, msg):
            self.msg = [m.tobytes() for m in msg]

    x = Protocol()
    data = b''.join(msg_to_bytes([b'asdf', b'asdf', b'asdf']))
    with pytest.raises(Exception):
        x.data_received(data)

    x = Protocol2()
    x.data_received(data)

def test_protocol():
    class FakeTransport:
        def __init__(self, protocol):
            self.protocol = protocol

        def writelines(self, data):
            self.protocol.data_received(b''.join(data))

    def fake_connect(protocol1, protocol2):
        protocol1.connection_made(FakeTransport(protocol2))
        protocol2.connection_made(FakeTransport(protocol1))

    class Protocol(MessageProtocol):
        def __init__(self):
            MessageProtocol.__init__(self)
            self.msgs = []

        def process_msg(self, msg):
            self.msgs.append([m.tobytes() for m in msg])

        def get_msg(self):
            return self.msgs.pop(0)

    protocol1 = Protocol()
    protocol2 = Protocol()
    msgs = [
        [b'ASDF1', b'FSDA5'] * 1 ,
        [b'ASDF2', b'FSDA4'] * 2 ,
        [b'ASDF3', b'FSDA3'] * 4 ,
        [b'ASDF4', b'FSDA2'] * 8 ,
        [b'ASDF5', b'FSDA1'] * 16,

        [b'ASDF1', b'FSDA5'] * 1 ,
        [b'ASDF2', b'FSDA4'] * 2 ,
        [b'ASDF3', b'FSDA3'] * 4 ,
        [b'ASDF4', b'FSDA2'] * 8 ,
        [b'ASDF5', b'FSDA1'] * 16,]

    fake_connect(protocol1, protocol2)
    for msg in msgs:
        protocol1.send_msg(msg)
        assert all(x==y for x, y in zip(protocol2.get_msg(),
            msg))
