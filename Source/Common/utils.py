import os
import tempfile
import zlib

from time import time

def compress_file(fileobj):
    compressor = zlib.compressobj(1)
    for data in iter(lambda : fileobj.read(256 * 1024), b''):
        compressed_data = compressor.compress(data)
        if not compressed_data:
            compressed_data = compressor.flush(zlib.Z_FULL_FLUSH)
        yield compressed_data
    yield compressor.flush(zlib.Z_FINISH)

def send_compressed_file(sender, fileobj, *args, **kwargs):
    for block in compress_file(fileobj):
        sender((b'\x01', compressed_data), *args, **kwargs)
    sender((b'\x00', b''), *args, **kwargs)

def send_file(sender, file, *args, **kwargs):
    for data in iter(lambda : file.read(256 * 1024), b''):
        sender((b'\x01', data), *args, **kwargs)
    sender((b'\x00', b''), *args, **kwargs)


class SimpleTimer:
    def __init__(self):
        self.__start = time()

    def get(self):
        return time() - self.__start
