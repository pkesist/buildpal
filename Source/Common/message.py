import struct
import asyncio

def msg_to_bytes(msg):
    def msg_to_bytes_gen(msg):
        yield struct.pack('!H', len(msg))
        for part in msg:
            yield struct.pack('!I', len(part))
            yield part
    return msg_to_bytes_gen(msg), sum(len(m) for m in msg) + (4 * len(msg)) + 2

def msg_from_bytes(byte_data):
    # TODO:
    # We want read-only memory views here. Unfortunately, when created
    # from bytearray, they are writable and consequently cannot be
    # hashed. I found no way of converting bytearray to bytes without
    # making a copy.
    memview = memoryview(bytes(byte_data))
    offset = 0
    (len,) = struct.unpack('!H', memview[offset:offset+2])
    offset += 2
    for i in range(len):
        (part_len,) = struct.unpack('!I', memview[offset:offset+4])
        offset += 4
        yield memview[offset:offset+part_len]
        offset += part_len

class MessageProtocol(asyncio.Protocol):
    def __init__(self):
        self.len_buff = bytearray(4)
        self.len_offset = 0
        self.msg_len = None
        self.msg_data = None
        self.msg_offset = 0

    def connection_made(self, transport):
        self.transport = transport

    def send_msg(self, msg):
        data, length = msg_to_bytes(msg)
        buffers = [struct.pack('!I', length)]
        buffers.extend(data)
        self.transport.writelines(buffers)

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
                    self.msg_data = bytearray(self.msg_len)
                    self.msg_offset = 0
            else:
                remaining = self.msg_len - self.msg_offset
                to_add = min(remaining, len(data) - data_offset)
                self.msg_data[self.msg_offset:self.msg_offset + to_add] = \
                    data[data_offset:data_offset + to_add]
                self.msg_offset += to_add
                data_offset += to_add

                if to_add == remaining:
                    msg = tuple(msg_from_bytes(self.msg_data))
                    self.process_msg(msg)
                    self.msg_len = None
                    self.msg_data = None
                    self.msg_offset = 0

    def process_msg(self, msg):
        raise NotImplementedError()


