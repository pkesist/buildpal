import asyncio
import struct
import sys

from io import BytesIO

class MemoryViewWrapper:
    def __init__(self, obj):
        self.obj = obj

    def __hash__(self):
        return self.obj.tobytes().__hash__()

    def __getitem__(self, index):
        return self.obj.__getitem__(index)

    def __eq__(self, obj):
        return self.obj == obj

    def tobytes(self):
        return self.obj.tobytes()

    def decode(self):
        return self.obj.tobytes().decode()

    def memory(self):
        return self.obj

def msg_to_bytes(msg):
    total_len = sum(len(m) for m in msg) + (4 * len(msg)) + 2
    yield struct.pack('!I', total_len)
    yield struct.pack('!H', len(msg))
    for part in msg:
        yield struct.pack('!I', len(part))
        yield part

def msg_from_bytes(memview):
    offset = 0
    (len,) = struct.unpack('!H', memview[offset:offset+2])
    offset += 2
    for i in range(len):
        (part_len,) = struct.unpack('!I', memview[offset:offset+4])
        offset += 4
        yield MemoryViewWrapper(memview[offset:offset+part_len])
        offset += part_len

class MessageProtocol(asyncio.Protocol):
    def __init__(self):
        self.len_buff = bytearray(4)
        self.len_offset = 0
        self.msg_len = None
        self.msg_data = BytesIO()
        self.msg_offset = 0
        self.transport = None

    def close(self):
        if self.transport:
            # Calling self.transport.close() from an event handler seems to
            # cause errors, even if from a completely unrelated connection
            # (but in the same loop).
            self.transport._loop.call_soon(self.transport.close)

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        self.transport = None

    def send_msg(self, msg):
        if self.transport:
            self.transport.writelines(msg_to_bytes(msg))

    def data_received(self, data):
        data_offset = 0
        messages = []
        while data_offset != len(data):
            if not self.msg_len:
                remaining = len(self.len_buff) - self.len_offset
                to_add = min(remaining, len(data) - data_offset)
                self.len_buff[self.len_offset:self.len_offset + to_add] = \
                    data[data_offset:data_offset + to_add]
                self.len_offset += to_add
                data_offset += to_add

                if to_add == remaining:
                    (self.msg_len,) = struct.unpack('!I', self.len_buff)
                    self.len_offset = 0
                    self.msg_data.seek(0)
            else:
                remaining = self.msg_len - self.msg_data.tell()
                to_add = min(remaining, len(data) - data_offset)
                self.msg_data.write(data[data_offset:data_offset + to_add])
                data_offset += to_add

                if to_add == remaining:
                    self.process_msg(tuple(msg_from_bytes(self.msg_data.getbuffer()[:self.msg_len])))
                    assert sys.getrefcount(self.msg_data) == 2, "never store message references!"
                    self.msg_len = None

    def process_msg(self, msg):
        raise NotImplementedError()
