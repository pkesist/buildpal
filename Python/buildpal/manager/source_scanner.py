from .gui_event import GUIEvent

from buildpal.common import SimpleTimer

import preprocessing
import os

from collections import defaultdict
from multiprocessing import cpu_count
from queue import Queue, Empty
from socket import getfqdn
from threading import Thread
from time import time

def collect_headers(preprocessor, filename, includes, sysincludes, defines):
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
    return preprocessor.scan_headers(ppc, filename)

def dump_cache():
    print("Dumping cache.")
    cache.dump('cacheDump.txt')

def header_info(preprocessor, task):
    header_info, missing_headers = collect_headers(preprocessor, task['source'], task['includes'],
        task['sysincludes'], task['macros'])
    shared_file_list = []
    for dir, system, data in header_info:
        shared_files_in_dir = []
        # Headers which are relative to source file are not
        # considered as candidates for server cache, and are
        # always sent together with the source file.
        for file, relative, content, checksum in data:
            if not relative:
                shared_files_in_dir.append((file, checksum))
        shared_file_list.append((dir, system, shared_files_in_dir))
    return header_info, tuple(shared_file_list), missing_headers


class SourceScanner:
    def __init__(self, notify, update_ui, thread_count=cpu_count() + 1):
        preprocessing.clear_content_cache()
        self.cache = preprocessing.Cache()
        self.in_queue = Queue()
        self.out_queue = Queue()
        self.closing = False
        self.threads = set()
        for i in range(thread_count):
            thread = Thread(target=self.__process_task_worker, args=(notify, update_ui))
            self.threads.add(thread)
        for thread in self.threads:
            thread.start()
        self.hostname = getfqdn()

    def get_cache_stats(self):
        hits, misses = self.cache.get_stats()
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
        except Empty:
            return None

    def __process_task_worker(self, notify, update_ui):
        preprocessor = preprocessing.Preprocessor(self.cache)
        while True:
            try:
                task = self.in_queue.get(timeout=1)
                task.note_time('dequeued by preprocessor', 'waiting for preprocessor thread')
                try:
                    task.header_info, task.server_task_info['filelist'], task.missing_headers = \
                        header_info(preprocessor, task.preprocess_task_info)
                    task.note_time('preprocessed', 'preprocessing time')
                except Exception as e:
                    notify(task, e)
                else:
                    update_ui(GUIEvent.update_cache_stats, self.get_cache_stats())
                    notify(task)
            except Empty:
                if self.closing:
                    return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.closing = True
        for thread in self.threads:
            thread.join()
