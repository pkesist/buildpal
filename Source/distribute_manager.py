#! python3.3
from functools import cmp_to_key
from queue import Queue as IntraprocessQueue, Empty
from multiprocessing import Lock, Process, Pool, Queue as MultiprocessQueue
from multiprocessing.connection import Connection, Client
from multiprocessing.managers import BaseManager, SyncManager, BaseProxy
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

def prepare_task(task):
    return task.manager_prepare()

def compile_worker(task, client_id, timer, node_info, prepare_pool):
    try:
        client_conn = Client(address=r"\\.\pipe\{}".format(client_id), authkey=None)
        if hasattr(task, 'manager_prepare'):
            with timer.timeit('prepare'):
                start = time()
                if task.algorithm == 'SCAN_HEADERS':
                    task.tempfile = prepare_pool.async_run(prepare_task, task)

                if task.algorithm == 'PREPROCESS_LOCALLY':
                    # Signal the client to do preprocessing.
                    client_conn.send('PREPROCESS')
                    # Wait for 'done'.
                    done = client_conn.recv()
                    assert done == 'DONE'

        with timer.timeit('find_available_node'):
            get_node_queue, return_node_queue = get_node_queues()
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
        with timer.timeit('recycle'):
            return_node_queue.put((node_index, server_conn))
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
            return_node_queue = MultiprocessQueue()
            get_node_queue = MultiprocessQueue(2)
            with BookKeepingManager() as book_keeper, \
                Pool(processes=self.__max_processes, initializer=set_node_queues, initargs=(get_node_queue, return_node_queue)) as compile_pool:
                node_info = book_keeper.NodeInfoHolder(len(self.__nodes))
                timer = book_keeper.Timer()
                prepare_pool = book_keeper.ProcessPool(4)
                node_finders = [NodeFinder(self.__nodes, node_info, get_node_queue, return_node_queue, timer) for node in range(1)]
                for node_finder in node_finders:
                    node_finder.start()
                while True:
                    self.print_stats(node_info, timer.as_dict())
                    try:
                        task, client_id = self.__task_queue.get(timeout=2)
                        compile_pool.apply_async(compile_worker, args=(task, client_id, timer, node_info, prepare_pool))
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
                'Completed {:<3} Failed {:<3} Running {:<3} Average Time {:<3} Ratio {:<3}\n'.format(
                node[0],
                node[1],
                node_info.tasks_sent      (index),
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

task_queue = MultiprocessQueue()

get_node_queue = None
return_node_queue = None

def set_node_queues(get, ret):
    global get_node_queue, return_node_queue
    get_node_queue = get
    return_node_queue = ret

def get_node_queues():
    global get_node_queue, return_node_queue
    return get_node_queue, return_node_queue

class NodeInfoHolder:
    class NodeInfo:
        def __init__(self):
            self._tasks_completed = 0
            self._tasks_failed    = 0
            self._tasks_sent      = 0
            self._total_time      = 0

    def __init__(self, size):
        self.__nodes = tuple((NodeInfoHolder.NodeInfo() for i in range(size)))

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
    def __init__(self, nodes, node_info, outgoing_queue, incoming_queue, timer):
        super(NodeFinder, self).__init__()
        self.__nodes = nodes
        self.__node_info = node_info
        self.__recycled_nodes = {}
        self.__incoming_queue = incoming_queue
        self.__outgoing_queue = outgoing_queue
        self.__timer = timer

    def process_incoming(self):
        try:
            node_index, conn = self.__incoming_queue.get_nowait()
            self.__recycled_nodes.setdefault(node_index, []).append(conn)
        except Empty:
            pass

    def run(self):
        while True:
            self.process_incoming()
            node = self.get_node()
            if node:
                self.__outgoing_queue.put(node)
            else:
                sleep(1)

    def get_node(self):
        def cmp(lhs, rhs):
            lhs_tasks_processing = self.__node_info.tasks_processing(lhs)
            rhs_tasks_processing = self.__node_info.tasks_processing(rhs)
            lhs_average_time = self.__node_info.average_time(lhs)
            rhs_average_time = self.__node_info.average_time(rhs)
            if lhs_average_time == 0 and rhs_average_time == 0:
                return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
            if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
                return -1 if lhs_average_time < rhs_average_time else 1
            return -1 if lhs_tasks_processing * lhs_average_time <= rhs_tasks_processing * rhs_average_time else 1
        
        node_index = min(range(len(self.__nodes)), key=cmp_to_key(cmp))
        recycled = self.__recycled_nodes.setdefault(node_index, [])
        if recycled:
            server_conn = recycled[0]
            del recycled[0]
        else:
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
