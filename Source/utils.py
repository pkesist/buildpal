import os
import subprocess
import tempfile
import zlib
import zmq

from time import time

class TempFile:
    """
        A more useful tempfile object which allows multiple open/close calls.
    """
    class Opener:
        def __init__(self, filename, mode):
            self.__filename = filename
            self.__file = open(filename, mode)
        
        def __enter__(self):
            return self.__file

        def __exit__(self, exc_type, exc_value, traceback):
            self.__file.close()

    def __init__(self, *args, **kwargs):
        file, filename = tempfile.mkstemp(*args, **kwargs)
        os.close(file)
        self.__filename = filename

    def open(self, mode):
        return TempFile.Opener(self.__filename, mode)

    def filename(self):
        return self.__filename

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.__filename)
        except Exception:
            pass


def get_batch_file_environment_side_effects(batch, args):
    """
        Returns a dictionary containing side-effects made by the given batch
        file.
    """
    delimiter = "TEMP_FILE_TESTER_DELIMITER_1351361363416436"
    test_batch_name = None
    with TempFile(suffix=".bat") as test_batch:
        with test_batch.open('wt') as test_batch_file:
            test_batch_file.write("""
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
        with subprocess.Popen(test_batch.filename(), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
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

def receive_file(receiver, fileobj):
    more = b'\x01'
    while more == b'\x01':
        more, data = receiver()
        fileobj.write(data)

def send_compressed_file(sender, fileobj, *args, **kwargs):
    compressor = zlib.compressobj(1)
    for data in iter(lambda : fileobj.read(256 * 1024), b''):
        sender((b'\x01', compressor.compress(data)), *args, **kwargs)
    sender((b'\x00', compressor.flush(zlib.Z_FINISH)), *args, **kwargs)

def receive_compressed_file(receiver, fileobj):
    more = b'\x01'
    decompressor = zlib.decompressobj()
    while more == b'\x01':
        more, data = receiver()
        fileobj.write(decompressor.decompress(data))
    fileobj.write(decompressor.flush())

def send_file(sender, file, *args, **kwargs):
    for data in iter(lambda : file.read(256 * 1024), b''):
        sender((b'\x01', data), *args, **kwargs)
    sender((b'\x00', b''), *args, **kwargs)

def relay_file(source_read, target_send):
    more = b'\x01'
    while more == b'\x01':
        more, data = source_read()
        target_send((more, data))

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

