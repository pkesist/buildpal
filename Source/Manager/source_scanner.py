from .scan_headers import collect_headers, cache_info

from Common import SimpleTimer

import os
import queue
import threading

from multiprocessing import cpu_count
from time import time

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
    def __init__(self, notify):
        self.in_queue = queue.Queue()
        self.out_queue = queue.Queue()
        self.closing = False
        self.threads = set()
        for i in range(cpu_count() + 1):
            thread = threading.Thread(target=self.__process_task_worker, args=(notify,))
            self.threads.add(thread)
        for thread in self.threads:
            thread.start()

    def add_task(self, task):
        self.in_queue.put((task, SimpleTimer()))

    def completed_task(self):
        try:
            return self.out_queue.get(block=False)
        except queue.Empty:
            return None

    def __process_task_worker(self, notify):
        while True:
            try:
                task, queued_timer = self.in_queue.get(timeout=1)
                time_in_queue = queued_timer.get()
                hi = header_info(task.preprocess_task_info)
                self.out_queue.put((task.client_conn.id, hi, time_in_queue,
                    queued_timer.get() - time_in_queue, time(), cache_info()))
                notify()

            except queue.Empty:
                if self.closing:
                    return

    def close(self):
        self.closing = True
        for thread in self.threads:
            thread.join()
