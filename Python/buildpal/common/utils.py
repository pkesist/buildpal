import zlib
import pstats
import cProfile

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
        sender((b'\x01', block), *args, **kwargs)
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

class Profiler:
    def __init__(self):
        self.stats = pstats.Stats()

    def __enter__(self):
        self.profile = cProfile.Profile()
        self.profile.enable()

    def __exit__(self, exc_type, exc_value, traceback):
        self.profile.disable()
        self.stats.add(self.profile)

    def print(self):
        self.stats.sort_stats('cumtime')
        self.stats.print_stats()

class Timer:
    def __init__(self):
        self.times = []
        self.time_point_names = []
        self.time_interval_names = []

    def note_time(self, time_point_name, time_interval_name=None):
        curr_time = time()
        self.times.append(curr_time)
        self.time_point_names.append(time_point_name)
        self.time_interval_names.append(time_interval_name)

    def time_points(self):
        return enumerate(zip(self.time_point_names, self.times))

    def time_durations(self):
        return ((x - 1, (self.time_interval_names[x],
            self.times[x] - self.times[x - 1])) \
            for x in range(1, len(self.time_interval_names)))
