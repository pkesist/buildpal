#! python3.3
from functools import cmp_to_key
from queue import Empty
from multiprocessing import Lock, Process, Pool, Queue
from multiprocessing.connection import Connection, Client
from multiprocessing.managers import BaseManager, SyncManager, BaseProxy
from threading import Lock as ThreadLock
from time import sleep, time

import configparser
import operator
import os
import socket
import sys

class ScopedTimer:
    def __init__(self, callable):
        self.__callable = callable
        self.__start = time()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__callable(time() - self.__start)

class Timer:
    def __init__(self):
        self.__times = {}

    def add_time(self, type, value):
        current = self.__times.get(type, (0, 0))
        self.__times[type] = (current[0] + value, current[1] + 1)

    def as_dict(self):
        return self.__times

class TimerProxy(BaseProxy):
    _exposed_ = ('add_time', 'as_dict', 'timeit')
    def add_time(self, type, value):
        return self._callmethod('add_time', (type, value))

    def as_dict(self):
        return self._callmethod('as_dict')

    def timeit(self, name):
        return ScopedTimer(lambda value : self.add_time(name, value))

def prepare_task(task, pth_file):
    return task.manager_prepare(pth_file)

class PTHFileRepository:
    def __init__(self):
        self.__lock = ThreadLock()
        self.__files = {}

    def acquire(self):
        self.__lock.acquire()

    def release(self):
        self.__lock.release()

    def registered(self, file, timestamp):
        return file in self.__files and self.__files[file] >= timestamp

    def register(self, file):
        self.__files[file] = os.stat(file).st_mtime

def compile_worker(task, client_id, timer, node_info, prepare_pool, pth_file_repository):
    try:
        client_conn = Client(address=r"\\.\pipe\{}".format(client_id), authkey=None)
        if task.pch_header:
            for include_path in task.preprocessor_info.includes:
                pch_header = os.path.join(include_path, task.pch_header)
                if os.path.exists(pch_header):
                    found = True
                    break
            assert found or not "Could not locate precompiled header '{}'".format(task.pch_header)
            pth_file = os.path.splitext(task.pch_file[0])[0] + '.clang.pth'
            pth_file_repository.acquire()
            try:
                if not pth_file_repository.registered(pth_file, os.stat(pch_header).st_mtime):
                    with timer.timeit('create_pth'):
                        from scan_headers import create_pth
                        create_pth(task.pch_header,
                            pth_file,
                            task.preprocessor_info.includes,
                            task.preprocessor_info.sysincludes,
                            task.preprocessor_info.all_macros)
                        pth_file_repository.register(pth_file)
            finally:
                pth_file_repository.release()
        else:
            pth_file = None

        with timer.timeit('prepare'):
            start = time()
            if task.algorithm == 'SCAN_HEADERS':
                task.tempfile = prepare_pool.async_run(prepare_task, task, pth_file)

            if task.algorithm == 'REWRITE_INCLUDES':
                task.tempfile = prepare_pool.async_run(prepare_task, task, pth_file)
                print("PREPARED FOR REWRITE", task.tempfile)

        with timer.timeit('find_available_node'):
            get_node_queue = get_node_queues()
            node_index, server_conn = get_node_queue.get()

        node_info.add_tasks_sent(node_index)
        with timer.timeit('send'):
            server_conn.send(task)
        task.manager_send(client_conn, server_conn, prepare_pool, timer)

        # Just block
        with timer.timeit('server_time'), ScopedTimer(lambda value : node_info.add_total_time(node_index, value)):
            server_status = server_conn.recv()
            if server_status == "SERVER_FAILED":
                return None

        assert server_status == "SERVER_DONE"
        with timer.timeit('receive'):
            task.manager_receive(client_conn, server_conn, timer)
            node_info.add_tasks_completed(node_index)
            node_info.connection_closed(node_index)
    except Exception:
        import traceback
        traceback.print_exc()

class TaskProcessor(Process):
    def __init__(self, nodes, task_queue, max_processes):
        self.__task_queue = task_queue
        self.__nodes = nodes
        self.__max_processes = max_processes

        super(TaskProcessor, self).__init__()

    def run(self):
        try:
            get_node_queue = Queue(32)
            with BookKeepingManager() as book_keeper, \
                Pool(processes=self.__max_processes, initializer=set_node_queues, initargs=(get_node_queue,)) as compile_pool:
                pth_files = book_keeper.PTHFileRepository()
                node_info = book_keeper.NodeInfoHolder(len(self.__nodes))
                timer = book_keeper.Timer()
                prepare_pool = book_keeper.ProcessPool(4)
                node_finders = [NodeFinder(self.__nodes, node_info, get_node_queue, timer) for node in range(8)]
                for node_finder in node_finders:
                    node_finder.start()
                while True:
                    self.print_stats(node_info, timer.as_dict())
                    try:
                        task, client_id = self.__task_queue.get(timeout=2)
                        compile_pool.apply_async(compile_worker, args=(task, client_id, timer, node_info, prepare_pool, pth_files))
                    except Empty:
                        pass
        finally:
            for node_finders in node_finders:
                node_finders.terminate()

    def print_stats(self, node_info, times):
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:15}:{:5} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Average Time {:<3.2f} Ratio {:<3.2f}\n'.format(
                node[0],
                node[1],
                node_info.tasks_sent      (index),
                node_info.connections     (index),
                node_info.tasks_completed (index),
                node_info.tasks_failed    (index),
                node_info.tasks_processing(index),
                node_info.average_time    (index),
                node_info.completion_ratio(index)))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
        sorted_times.sort(key=operator.itemgetter(3), reverse=True)
        for name, time, count, average in sorted_times:
            print('{:-<30} Total {:->10.2f} Num {:->5} Average {:->10.2f}'.format(name, time, count, average))

task_queue = Queue()

get_node_queue = None

def set_node_queues(get):
    global get_node_queue
    get_node_queue = get

def get_node_queues():
    global get_node_queue
    return get_node_queue

class NodeInfoHolder:
    class NodeInfo:
        def __init__(self):
            self._tasks_completed  = 0
            self._tasks_failed     = 0
            self._tasks_sent       = 0
            self._total_time       = 0
            self._open_connections = 0

    def __init__(self, size):
        self.__nodes = tuple((NodeInfoHolder.NodeInfo() for i in range(size)))

    def connection_open(self, index): self.__nodes[index]._open_connections += 1

    def connection_closed(self, index): self.__nodes[index]._open_connections -= 1

    def connections(self, index): return self.__nodes[index]._open_connections

    def tasks_sent(self, index): return self.__nodes[index]._tasks_sent

    def tasks_completed(self, index): return self.__nodes[index]._tasks_completed

    def tasks_failed(self, index): return self.__nodes[index]._tasks_failed

    def tasks_processing(self, index): return self.tasks_sent(index) - self.tasks_completed(index) - self.tasks_failed(index)

    def total_time(self, index): return self.__nodes[index]._total_time

    def average_time(self, index):
        tasks_completed = self.tasks_completed(index)
        return self.total_time(index) / tasks_completed if tasks_completed else 0

    def add_tasks_sent(self, index): self.__nodes[index]._tasks_sent += 1

    def dec_tasks_sent(self, index): self.__nodes[index]._tasks_sent -= 1

    def add_tasks_completed(self, index): self.__nodes[index]._tasks_completed += 1

    def add_tasks_failed(self, index): self.__nodes[index]._add_tasks_failed += 1

    def add_total_time(self, index, value): self.__nodes[index]._total_time += value

    def completion_ratio(self, index):
        if not self.tasks_sent(index):
            return 1.0
        return self.tasks_completed(index) / self.tasks_sent(index)

class NodeFinder(Process):
    def __init__(self, nodes, node_info, outgoing_queue, timer):
        super(NodeFinder, self).__init__()
        self.__nodes = nodes
        self.__node_info = node_info
        self.__outgoing_queue = outgoing_queue
        self.__timer = timer

    def run(self):
        while True:
            node = self.get_node()
            if node:
                self.__outgoing_queue.put(node)
            else:
                sleep(1)

    def get_node(self):
        def cmp(lhs, rhs):
            #lhs_tasks_processing = self.__node_info.tasks_processing(lhs)
            #rhs_tasks_processing = self.__node_info.tasks_processing(rhs)
            lhs_tasks_processing = self.__node_info.connections(lhs)
            rhs_tasks_processing = self.__node_info.connections(rhs)
            lhs_average_time = self.__node_info.average_time(lhs)
            rhs_average_time = self.__node_info.average_time(rhs)
            if lhs_average_time == 0 and rhs_average_time == 0:
                return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
            if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
                return -1 if lhs_average_time < rhs_average_time else 1
            return -1 if lhs_tasks_processing * lhs_average_time <= rhs_tasks_processing * rhs_average_time else 1
        
        node_index = min(range(len(self.__nodes)), key=cmp_to_key(cmp))
        node = self.__nodes[node_index]
        try:
            with socket.socket(getattr(socket, 'AF_INET')) as s:
                s.settimeout(1)
                s.connect(node)
                s.settimeout(None)
                server_conn = Connection(s.detach())
        except Exception:
            print("Failed to connect to '{}'".format(node))
            return None
        accept = server_conn.recv()
        if accept == "ACCEPT":
            self.__node_info.connection_open(node_index)
            return node_index, server_conn
        else:
            assert accept == "REJECT"
            return None

class ProcessPool:
    def __init__(self, processes):
        self.__prepare_pool = Pool(processes=processes)
        self.__async_tasks = {}
        self.__counter = 0

    def async_run(self, callable, *args, **kwds):
        id = self.__counter
        self.__counter += 1
        self.__async_tasks[id] = self.__prepare_pool.apply_async(callable, args=args, kwds=kwds)
        return id

    def get_result(self, id):
        result = self.__async_tasks[id].get()
        del self.__async_tasks[id]
        return result

class BookKeepingManager(SyncManager):
    pass

BookKeepingManager.register('ProcessPool', ProcessPool)
BookKeepingManager.register('Timer', Timer, TimerProxy)
BookKeepingManager.register('NodeInfoHolder', NodeInfoHolder)
BookKeepingManager.register('PTHFileRepository', PTHFileRepository)

def queue_task(task, client_id):
    task_queue.put((task, client_id))

class QueueManager(BaseManager):
    pass

QueueManager.register('queue_task', callable=queue_task)

default_script = 'distribute_manager.ini'

if __name__ == "__main__":
    if len(sys.argv) == 2:
        iniFile = os.path.join(os.getcwd(), sys.argv[1])
    else:
        iniFile = os.path.join(os.getcwd(), default_script)
    if not os.path.isfile(iniFile):
        print("""
Usage:
    {} [<ini-file>]

    If no <ini-file> is specified, script will attept to use '{}'
    in the current directory.
""").format(sys.argv[0], default_script)
        raise SystemExit()

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(iniFile):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(iniFile))

    manager_section = 'Manager'
    nodes_section = 'Build Nodes'

    id = config.get(manager_section, 'id')
    max_processes = config.getint(manager_section, 'max_processes', fallback=None)

    if not nodes_section in config:
        raise "ERROR: No '{}' section in '{}'.".format(nodes_section, iniFile)

    nodes = []
    section = config[nodes_section]
    done = False
    while not done:
        option = "node[{}]".format(len(nodes))
        if option in section:
            value = section[option]
            delim = ':'
            if not delim in value:
                raise RuntimeError("Invalid node value. Node values should be given as <host>:<port>")
            index = value.index(delim)
            nodes.append((value[:index], int(value[index+1:])))
        else:
            done = True
    if not nodes:
        raise RuntimeErrors("No build nodes configured.")

    if max_processes is None:
        max_processes = 4 * len(nodes)
   
    task_processor = TaskProcessor(nodes, task_queue, max_processes=max_processes)
    task_processor.start()

    queue_manager = QueueManager(r"\\.\pipe\{}".format(id), b"")
    server = queue_manager.get_server()
    server.serve_forever()
