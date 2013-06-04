#! python3.3
from queue import PriorityQueue, Empty
from multiprocessing import Lock, Process, Pool, Queue, Value, RawValue
from multiprocessing.connection import Client
from multiprocessing.managers import BaseManager, SyncManager
from time import sleep, time

import ctypes
import heapq
import sys
import os
import configparser

class Timer:
    class ScopedTimer:
        def __init__(self, name, timer):
            self.__timer = timer
            self.__start = time()
            self.__name = name

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.__timer.add_time(self.__name, time() - self.__start)

    def __init__(self, times):
        self.__times = times

    def add_time(self, type, value):
        current = self.__times.get(type, (0, 0))
        self.__times[type] = (current[0] + value, current[1] + 1)

    def timeit(self, name):
        return Timer.ScopedTimer(name, self)

def prepare_task(task):
    return task.manager_prepare()

class Worker:
    def __init__(self, wrapped_task, client_conn, times, task_map, nodes, node_info, prepare_pool):
        self.__timer = Timer(times)
        self.__client_conn = client_conn
        self.__wrapped_task = wrapped_task
        self.__task_map = task_map
        self.__nodes = nodes
        self.__node_info = node_info
        self.__original = True
        self.__prepare_pool = prepare_pool

    def wrapped_task(self): return self.__wrapped_task

    def process_task(self, node_index):
        with self.__timer.timeit('send'):
            self.wrapped_task().task().manager_send(self.__client_conn, self.__server_conn)

        if self.__original:
            self.__node_info.add_new_task_sent(node_index)
        else:
            self.__node_info.add_old_task_sent(node_index)

        # Just block
        with self.__timer.timeit('server_time'):
            done = self.__server_conn.recv()
            assert done == "SERVER_DONE"

        with self.__server_conn:
            if not self.wrapped_task().try_mark_completed():
                self.__server_conn.send(False)
                return False

            self.__server_conn.send(True)
            with self.__timer.timeit('receive'):
                result = self.wrapped_task().task().manager_receive(self.__client_conn, self.__server_conn)
                return result

    def __call__(self):
        try:
            task = self.wrapped_task().task()
            if hasattr(task, 'manager_prepare'):
                with self.__timer.timeit('prepare'):
                    start = time()
                    if task.algorithm == 'SCAN_HEADERS':
                        task.tempfile = self.__prepare_pool.run(prepare_task, (task,))
                        if not task.tempfile:
                            raise RuntimeError("Failed to preprocess.")
                            #task.algorithm = 'PREPROCESS_LOCALLY'

                    if task.algorithm == 'PREPROCESS_LOCALLY':
                        # Signal the client to do preprocessing.
                        self.__client_conn.send('PREPROCESS')
                        # Wait for 'done'.
                        done = self.__client_conn.recv()
                        assert done == 'DONE'

            with self.__timer.timeit('find_available_node'):
                find_node_result = self.find_available_node()
                if find_node_result is None:
                    return
            node_index, server_conn = find_node_result
            self.__server_conn = server_conn
            self.__task_map.setdefault(self.wrapped_task().client_id(), set()).add(node_index)

            with self.__timer.timeit('run_task'):
                # Create and run worker.
                result = self.process_task(node_index)
                # Did not process it after all.
                if result is None:
                    return

                if result:
                    self.__node_info.add_tasks_completed(node_index)
                else:
                    self.__node_info.add_tasks_failed(node_index)
        except Exception:
            import traceback
            traceback.print_exc()

    def find_available_node(self):
        nodes_processing_task = self.__task_map.get(self.__wrapped_task.client_id(), set())
        first = None
        accepted = False
        rejections = 0

        def ordering_key(index):
            return self.__node_info.completion_ratio(index), self.__node_info.tasks_processing(index), self.__node_info.tasks_failed(index)

        best_nodes = list(((ordering_key(index), self.__nodes[index], index)
                for index in range(len(self.__nodes)) if not index in nodes_processing_task))
        if not best_nodes:
            return
        best_nodes.sort(reverse=True)
        while not accepted:
            for entry in best_nodes:
                ordering_key, node, node_index = entry
                if not first:
                    first = node
                elif node == first:
                    # If everyone rejected task.
                    if nodes_processing_task:
                        return
                    else:
                        sleep(1)

                try:
                    server_conn = Client(address=node)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    continue
                with self.__timer.timeit('accept_time'):
                    server_conn.send(self.__wrapped_task.task())
                    try:
                        accepted, has_compiler = server_conn.recv()
                        if not accepted:
                            rejections += 1
                            server_conn.close()
                        else:
                            return node_index, server_conn
                    except IOError:
                        pass

class WrapTask:
    def __init__(self, task, client_id, manager):
        self.__client_id = client_id
        self.__task = task
        self.__completed = manager.Value('bool', False)
        self.__nodes_processing = manager.list()

    def is_completed(self):
        return self.__completed.value

    def try_mark_completed(self):
        original = self.__completed.value
        self.__completed.value = True
        return not original

    def task(self):
        return self.__task

    def client_id(self):
        return self.__client_id

    def nodes_processing(self):
        return self.__nodes_processing

class TaskProcessor(Process):
    def __init__(self, nodes, queue):
        self.__queue = queue
        self.__nodes = nodes
        self.__tasks = {}
        self.__processes = []

        super(TaskProcessor, self).__init__()

    def run(self):
        self.__compile_pool = Pool(processes=32)

        self.__manager = BookKeepingManager()
        self.__manager.start()

        self.__node_info = self.__manager.NodeInfoHolder(len(self.__nodes))
        self.__task_map = self.__manager.dict()
        self.__times = self.__manager.dict()
        self.__timer = Timer(self.__times)
        self.__prepare_pool = self.__manager.ProcessPool(4)

        self.print_stats()
        count = 0
        while True:
            count += 1
            if self.run_one() or not count % 10:
                self.print_stats()

    def run_one(self):
        try:
            task, client_id = self.__queue.get(timeout=0.2)
            wrapped_task = WrapTask(task, client_id, self.__manager) 
            client_conn = Client(address=r"\\.\pipe\{}".format(client_id), authkey=None)
            self.__tasks[client_id] = wrapped_task, client_conn
            worker = Worker(wrapped_task, client_conn, self.__times, self.__task_map, self.__nodes, self.__node_info, self.__prepare_pool)
            self.__compile_pool.apply_async(worker)
            return True
        except Empty:
            return False

    def join_dead_processes(self):
        dead=list(filter(lambda p : not p.is_alive(), self.__processes))
        self.__processes=[p for p in self.__processes if p not in dead]
        for p in self.__processes:
            p.join(0)
        return bool(dead)

    def print_stats(self):
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:15}:{:5} - New sent {:<3} Old sent {:<3} '
                'Completed {:<3} Failed {:<3} Running {:<3} Ratio {:<3}\n'.format(
                node[0],
                node[1],
                self.__node_info.new_tasks_sent  (index),
                self.__node_info.old_tasks_sent  (index),
                self.__node_info.tasks_completed (index),
                self.__node_info.tasks_failed    (index),
                self.__node_info.tasks_processing(index),
                self.__node_info.completion_ratio(index)))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        times = self.__times._getvalue()
        for time in times:
            print('{:-<30} Total {:10.2f} - Num {:<5} - Average {:10.2f}'.format(time, times[time][0], times[time][1], times[time][0] / times[time][1]))

task_queue = Queue()

class NodeInfoHolder:
    class NodeInfo:
        def __init__(self):
            self._tasks_completed = 0
            self._tasks_failed    = 0
            self._new_tasks_sent  = 0
            self._old_tasks_sent  = 0
    def __init__(self, size):
        self.__nodes = tuple((NodeInfoHolder.NodeInfo() for i in range(size)))

    def new_tasks_sent(self, index): return self.__nodes[index]._new_tasks_sent

    def old_tasks_sent(self, index): return self.__nodes[index]._old_tasks_sent

    def tasks_completed(self, index): return self.__nodes[index]._tasks_completed

    def tasks_failed(self, index): return self.__nodes[index]._tasks_failed

    def tasks_sent(self, index): return self.new_tasks_sent(index) + self.old_tasks_sent(index)

    def tasks_processing(self, index): return self.tasks_sent(index) - self.tasks_completed(index) - self.tasks_failed(index)

    def add_new_task_sent(self, index): self.__nodes[index]._new_tasks_sent += 1

    def add_old_task_sent(self, index): self.__nodes[index]._old_tasks_sent += 1

    def add_tasks_completed(self, index): self.__nodes[index]._tasks_completed += 1

    def add_tasks_failed(self, index): self.__nodes[index]._add_tasks_failed += 1

    def completion_ratio(self, index):
        if not self.tasks_sent(index):
            return 1.0
        return self.tasks_completed(index) / self.tasks_sent(index)

class ProcessPool:
    def __init__(self, processes):
        self.__prepare_pool = Pool(processes=processes)

    def run(self, callable, args=(), kwds={}):
        return self.__prepare_pool.apply(callable, args=args, kwds=kwds)

class BookKeepingManager(SyncManager):
    pass

BookKeepingManager.register('NodeInfoHolder', NodeInfoHolder)
BookKeepingManager.register('ProcessPool', ProcessPool)

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
   
    queue_manager = QueueManager(r"\\.\pipe\{}".format(id), b"")

    task_processor = TaskProcessor(nodes, task_queue)
    task_processor.start()

    server = queue_manager.get_server()
    server.serve_forever()
