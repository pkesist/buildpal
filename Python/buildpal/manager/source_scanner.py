from .gui_event import GUIEvent

import preprocessing

from multiprocessing import cpu_count
from queue import Queue
from threading import Thread

def collect_headers(preprocessor, filename, include_dirs, sysinclude_dirs,
        forced_includes, defines):
    preprocessor.set_ms_mode(True) # If MSVC.
    preprocessor.set_ms_ext(True) # Should depend on Ze & Za compiler options.
    ppc = preprocessing.PreprocessingContext()
    for path in include_dirs:
        ppc.add_include_path(path, False)
    for path in sysinclude_dirs:
        ppc.add_include_path(path, True)
    for define in defines:
        define = define.split('=')
        assert len(define) in (1, 2)
        macro = define[0]
        # /Dxxx is actually equivalent to /Dxxx=1.
        value = define[1] if len(define) == 2 else "1"
        ppc.add_macro(macro, value)
    for forced_include in forced_includes:
        ppc.add_forced_include(forced_include)
    return preprocessor.scan_headers(ppc, filename)

def header_info(preprocessor, preprocess_task):
    header_info, missing_headers = collect_headers(preprocessor,
        preprocess_task.source, preprocess_task.include_dirs,
        preprocess_task.sysinclude_dirs, preprocess_task.forced_includes,
        preprocess_task.macros)
    shared_file_list = []
    for dir, data in header_info:
        shared_files_in_dir = []
        # Headers which are relative to source file are not
        # considered as candidates for server cache, and are
        # always sent together with the source file.
        for file, relative, content_entry in data:
            if not relative:
                shared_files_in_dir.append((file, content_entry.checksum()))
        shared_file_list.append((dir, shared_files_in_dir))
    return header_info, tuple(shared_file_list), missing_headers


class SourceScanner:
    class ShutdownThread: pass

    def __init__(self, notify, update_ui, thread_count=cpu_count() + 1):
        preprocessing.clear_content_cache()
        self.cache = preprocessing.Cache()
        self.preprocessor = preprocessing.Preprocessor(self.cache)
        self.in_queue = Queue()
        self.closing = False
        self.threads = set()
        for _ in range(thread_count):
            thread = Thread(target=self.__process_task_worker, args=(notify, update_ui))
            self.threads.add(thread)
        for thread in self.threads:
            thread.start()

    def get_cache_stats(self):
        hits, misses = self.cache.get_stats()
        total = hits + misses
        if total == 0:
            total = 1
        return hits, misses, hits / total

    def add_task(self, task):
        task.note_time('queued for preprocessing')
        self.in_queue.put(task)

    def __process_task_worker(self, notify, update_ui):
        while True:
            task = self.in_queue.get()
            if task is self.ShutdownThread:
                return
            task.note_time('dequeued by preprocessor', 'waiting for preprocessor thread')
            try:
                task.header_info, task.server_task.filelist, task.missing_headers = \
                    header_info(self.preprocessor, task.preprocess_task)
                task.note_time('preprocessed', 'preprocessing time')
            except Exception as e:
                notify(task, e)
            else:
                update_ui(GUIEvent.update_cache_stats, self.get_cache_stats())
                update_ui(GUIEvent.update_preprocessed_count, self.preprocessor.files_preprocessed())
                notify(task)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        for thread in self.threads:
            self.in_queue.put(self.ShutdownThread)

        for thread in self.threads:
            thread.join()
