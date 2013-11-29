import os
import subprocess
import tempfile
import zlib
import zmq

from time import time

def get_batch_file_environment_side_effects(batch, args):
    """
        Returns a dictionary containing side-effects made by the given batch
        file.
    """
    delimiter = "TEMP_FILE_TESTER_DELIMITER_1351361363416436"
    test_batch_name = None
    fd, test_batch_filename = tempfile.mkstemp(suffix='.bat')
    with os.fdopen(fd, 'wt') as test_batch:
        test_batch.write("""
@echo off
echo {batch}
echo {delimiter}
set
echo {delimiter}
call "{batch}" {args}
echo {delimiter}
set
echo {delimiter}
""".format(batch=os.path.join(os.getcwd(), batch), args=" ".join(a for a in args), delimiter=delimiter))
    to_add={}
    with subprocess.Popen(test_batch_filename, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        stdout, stderr = proc.communicate()
        output = stdout.decode()
        output = output.split('\r\n')
        first = output.index(delimiter)
        second = output.index(delimiter, first + 1)
        third  = output.index(delimiter, second + 1)
        fourth = output.index(delimiter, third + 1)
        
        before = output[first + 1 : second - 1]
        after  = output[third + 1 : fourth - 1]
        added = [a for a in after if not a in before]
        removed = [b for b in before if not b in after]
        for a in added:
            eq = a.index('=')
            to_add[a[:eq].upper()] = a[eq+1:]
    return to_add

def send_compressed_file(sender, fileobj, *args, **kwargs):
    compressor = zlib.compressobj(1)
    for data in iter(lambda : fileobj.read(256 * 1024), b''):
        sender((b'\x01', compressor.compress(data)), *args, **kwargs)
    sender((b'\x00', compressor.flush(zlib.Z_FINISH)), *args, **kwargs)

def send_file(sender, file, *args, **kwargs):
    for data in iter(lambda : file.read(256 * 1024), b''):
        sender((b'\x01', data), *args, **kwargs)
    sender((b'\x00', b''), *args, **kwargs)

def bind_to_random_port(socket):
    socket.bind('tcp://*:*')
    address = socket.getsockopt(zmq.LAST_ENDPOINT)
    while address[-1] == 0:
        address = address[:-1]
    return int(address[address.index(b':', 4) + 1:])

class SimpleTimer:
    def __init__(self):
        self.__start = time()

    def get(self):
        return time() - self.__start

class Rendezvous:
    def __init__(self, first_name='add_first', second_name='add_second'):
        self._first = []
        self._second = []

        self.__dict__[first_name] = self.__add_first
        self.__dict__[second_name] = self.__add_second

    def first(self):
        return self._first

    def second(self):
        return self._second

    def __add_first(self, first):
        if self._second:
            second = self._second[0]
            del self._second[0]
            self.match(first, second)
        else:
            self._first.append(first)

    def __add_second(self, second):
        if self._first:
            first = self._first[0]
            del self._first[0]
            self.match(first, second)
        else:
            self._second.append(second)

    def match(self, first, second):
        raise NotImplementedError()


def create_socket(zmq_ctx, socket_type):
    socket = zmq_ctx.socket(socket_type)
    return socket


def recv_multipart(socket):
    # The 'cast' is here because PyZMQ sets memoryview.ndim to 0, causing index
    # operations to fail. Not really sure why they do that.
    return tuple(frame.buffer.cast('B') for frame in socket.recv_multipart(copy=False))
