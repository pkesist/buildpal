from .scan_headers import collect_headers, cache_info

from Common import SimpleTimer

import os
import queue

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import cpu_count


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
    for dir, data in header_info:
        for entry in data:
            abs = os.path.join(dir, entry[0])
            entry.append(header_beginning(abs))
    return header_info

class SourceScanner:
    def __init__(self):
        self.out_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(4 * cpu_count())

    def add_task(self, task):
        future = self.executor.submit(self.process_task_worker, task, SimpleTimer())
        def verify(f):
            f.result()
        future.add_done_callback(verify)

    def completed_task(self):
        return self.out_queue.get()

    def process_task_worker(self, task, queued_timer):
        queued_time = queued_timer.get()
        timer = SimpleTimer()
        hi = header_info(task.preprocess_task_info)
        result = (
            task.client_conn.id,
            hi,
            queued_time,
            timer.get(),
            cache_info())
        self.out_queue.put(result)

    def terminate(self):
        self.executor.shutdown()
        self.out_queue.put('DONE')
