from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Lock
from collections import defaultdict

import zlib

class Compressor:
    def __init__(self, poller):
        self.executor = ThreadPoolExecutor(2)
        self.poller = poller
        self.compressed_files_lock = Lock()
        self.compressed_files = []
        self.compressed_file_data = {}
        self.waiters = defaultdict(list)

    def compress(self, file, on_completion):
        self.compressed_files_lock.acquire()
        if file in self.compressed_files:
            self.compressed_files_lock.release()
            on_completion(BytesIO(self.compressed_file_data[file]))
        else:
            try:
                if file not in self.waiters:
                    event = self.poller.create_event(
                        lambda ev : self.__compression_completed(file, ev))
                    self.executor.submit(self.__do_compress, file
                        ).add_done_callback(lambda f : event())
                self.waiters.setdefault(file, []).append(on_completion)
            finally:
                self.compressed_files_lock.release()

    def __compression_completed(self, file, event):
        event.close()
        for on_completion in self.waiters[file]:
            on_completion(BytesIO(self.compressed_file_data[file]))
        del self.waiters[file]

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
            self.compressed_file_data[file] = buffer.read()
