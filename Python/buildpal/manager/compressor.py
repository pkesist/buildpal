from io import BytesIO
from threading import Lock
from collections import defaultdict

import zlib

class Compressor:
    def __init__(self, loop, executor):
        self.executor = executor
        self.loop = loop
        self.compressed_files_lock = Lock()
        self.compressed_files = []
        self.compressed_file_data = {}
        self.waiters = defaultdict(list)

    def compress_file(self, file, on_completion):
        self.compressed_files_lock.acquire()
        if file in self.compressed_files:
            self.compressed_files_lock.release()
            on_completion(BytesIO(self.compressed_file_data[file]))
        else:
            try:
                if file not in self.waiters:
                    self.executor.submit(self.__do_compress, file)
                self.waiters[file].append(on_completion)
            finally:
                self.compressed_files_lock.release()

    def __do_compress(self, file):
        buffer = BytesIO()
        compressor = zlib.compressobj(1)
        with open(file, 'rb') as fileobj:
            for data in iter(lambda : fileobj.read(256 * 1024), b''):
                buffer.write(compressor.compress(data))
        buffer.write(compressor.flush())
        buffer.seek(0)
        with self.compressed_files_lock:
            if len(self.compressed_file_data) > 4:
                del self.compressed_file_data[self.compressed_files.pop(0)]
            self.compressed_files.append(file)
            self.compressed_file_data[file] = buffer.getbuffer()
        def notify_waiters(byte_data, waiters):
            for on_completion in waiters:
                on_completion(BytesIO(byte_data))
        self.loop.call_soon_threadsafe(notify_waiters,
            self.compressed_file_data[file], self.waiters[file])
        del self.waiters[file]
