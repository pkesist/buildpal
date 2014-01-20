from .scan_headers import collect_headers, cache_info

from Common import SimpleTimer

import os
import queue
import threading

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
        self.in_queue = queue.Queue()
        self.out_queue = queue.Queue()
        self.terminating = False
        self.threads = set()
        for i in range(cpu_count() + 1):
            thread = threading.Thread(target=self.__process_task_worker)
            self.threads.add(thread)
        for thread in self.threads:
            thread.start()

    def add_task(self, task):
        self.in_queue.put((task, SimpleTimer()))

    def completed_task(self):
        return self.out_queue.get()

    def __process_task_worker(self):
        while True:
            try:
                task, queued_timer = self.in_queue.get(timeout=1)
                queued_time = queued_timer.get()
                hi = header_info(task.preprocess_task_info)
                self.out_queue.put((task.client_conn.id, hi, queued_time,
                    queued_timer.get() - queued_time, cache_info()))
            except queue.Empty:
                if self.terminating:
                    return

    def terminate(self):
        self.terminating = True
        for thread in self.threads:
            thread.join()
        self.out_queue.put(None)
