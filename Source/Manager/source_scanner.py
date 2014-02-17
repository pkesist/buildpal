from Common import SimpleTimer

import preprocessing
import os
import queue
import threading
import cProfile
import pstats

from collections import defaultdict
from multiprocessing import cpu_count
from socket import getfqdn
from time import time

data = threading.local()
cache = preprocessing.Cache()

def get_preprocessor():
    if not hasattr(data, 'pp'):
        data.pp = preprocessing.Preprocessor(cache)
    return data.pp

def collect_headers(filename, includes, sysincludes, defines, ignored_headers=[]):
    preprocessor = get_preprocessor()
    preprocessor.set_ms_mode(True) # If MSVC.
    preprocessor.set_ms_ext(True) # Should depend on Ze & Za compiler options.
    ppc = preprocessing.PreprocessingContext()
    for path in includes:
        ppc.add_include_path(path, False)
    for path in sysincludes:
        ppc.add_include_path(path, True)
    for define in defines:
        define = define.split('=')
        assert len(define) in (1, 2)
        macro = define[0]
        # /Dxxx is actually equivalent to /Dxxx=1.
        value = define[1] if len(define) == 2 else "1"
        ppc.add_macro(macro, value)
    for ignored_header in ignored_headers:
        ppc.add_ignored_header(ignored_header)
    return preprocessor.scan_headers(ppc, filename)

def dump_cache():
    print("Dumping cache.")
    cache.dump('cacheDump.txt')

def header_info(task):
    header_info = collect_headers(task['source'], task['includes'],
        task['sysincludes'], task['macros'],
        ignored_headers=[task['pch_header']] if task['pch_header'] else [])
    shared_file_list = []
    for dir, data in header_info:
        shared_files_in_dir = []
        # Headers which are relative to source file are not
        # considered as candidates for server cache, and are
        # always sent together with the source file.
        for file, relative, content, checksum in data:
            if not relative:
                shared_files_in_dir.append((file, checksum))
        shared_file_list.append((dir, shared_files_in_dir))
    return header_info, tuple(shared_file_list)


class SourceScanner:
    def __init__(self, notify, thread_count=cpu_count() + 1):
        self.in_queue = queue.Queue()
        self.out_queue = queue.Queue()
        self.closing = False
        self.threads = set()
        self.stats = pstats.Stats()
        for i in range(thread_count):
            thread = threading.Thread(target=self.__process_task_worker, args=(notify, self.stats))
            self.threads.add(thread)
        for thread in self.threads:
            thread.start()
        self.hostname = getfqdn()

    def get_cache_stats(self):
        hits, misses = cache.get_stats()
        total = hits + misses
        if total == 0:
            total = 1
        return (hits, misses, hits / total)

    def add_task(self, task):
        task.note_time('queued for preprocessing')
        task.server_task_info['fqdn'] = self.hostname
        self.in_queue.put(task)

    def completed_task(self):
        try:
            return self.out_queue.get(block=False)
        except queue.Empty:
            return None

    def __process_task_worker(self, notify, stats):
        #profile = cProfile.Profile()
        #profile.enable()
        while True:
            try:
                task = self.in_queue.get(timeout=1)
                task.note_time('dequeued by preprocessor')
                task.header_info, task.server_task_info['filelist'] = \
                    header_info(task.preprocess_task_info)
                task.note_time('preprocessed')
                # Synchronized by GIL.
                notify(task)
            except queue.Empty:
                if self.closing:
                    #profile.disable()
                    #stats.add(profile)
                    return

    def close(self):
        self.closing = True
        for thread in self.threads:
            thread.join()
        #self.stats.sort_stats('cumtime')
        #self.stats.print_stats()
