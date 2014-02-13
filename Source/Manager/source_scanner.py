from Common import SimpleTimer

import preprocessing
import os
import queue
import threading

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
        assert len(define) == 1 or len(define) == 2
        macro = define[0]
        # /Dxxx is actually equivalent to /Dxxx=1.
        value = define[1] if len(define) == 2 else "1"
        ppc.add_macro(macro, value)
    for ignored_header in ignored_headers:
        ppc.add_ignored_header(ignored_header)
    # Group result by dir.
    result = defaultdict(list)
    for dir, name, relative, buff, checksum in preprocessor.scan_headers(ppc, filename):
        result[dir].append([name, relative, buff, checksum])
    return tuple(result.items())

def dump_cache():
    print("Dumping cache.")
    cache.dump('cacheDump.txt')

def header_beginning(filename):
    # 'sourceannotations.h' header is funny. If you add a #line directive to
    # it it will start tossing incomprehensible compiler erros. It would
    # seem that cl.exe has some hardcoded logic for this header. Person
    # responsible for this should be severely punished.
    if 'sourceannotations.h' in filename:
        return b''
    pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
    return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

def header_info(task):
    header_info = collect_headers(task['source'], task['includes'],
        task['sysincludes'], task['macros'],
        ignored_headers=[task['pch_header']] if task['pch_header'] else [])
    filelist = []
    for dir, data in header_info:
        dir_data = []
        for entry in data:
            file, relative, content, checksum = entry
            abs = os.path.join(dir, file)
            entry.append(header_beginning(abs))
            if not relative:
                # Headers which are relative to source file are not
                # considered as candidates for server cache, and are
                # always sent together with the source file.
                dir_data.append((file, checksum))
        filelist.append((dir, dir_data))
    return header_info, tuple(filelist)


class SourceScanner:
    def __init__(self, notify, thread_count=cpu_count() + 1):
        self.in_queue = queue.Queue()
        self.out_queue = queue.Queue()
        self.closing = False
        self.threads = set()
        for i in range(thread_count):
            thread = threading.Thread(target=self.__process_task_worker, args=(notify,))
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

    def __process_task_worker(self, notify):
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
                    return

    def close(self):
        self.closing = True
        for thread in self.threads:
            thread.join()
