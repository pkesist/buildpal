#! python3
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

class Context:
    def add_time(self, type, value):
        self.times[type] = self.get_time(type) + value

    def get_time(self, type):
        return self.times.get(type, 0)

class Worker(Process):
    def __init__(self, wrapped_task, client_conn, times, task_map, nodes, node_info):
        ctx = Context()
        ctx.client_conn = client_conn
        ctx.times       = times

        self.__ctx = ctx

        self.__wrapped_task = wrapped_task
        self.__task_map = task_map
        self.__nodes = nodes
        self.__node_info = node_info
        self.__original = True

        super(Worker, self).__init__()

    def wrapped_task(self): return self.__wrapped_task

    def context(self):
        return self.__ctx

    def process_task(self, node_index):
        start = time()
        self.wrapped_task().task().manager_send(self.context())
        sent = time()
        self.context().add_time('send', sent - start)

        if self.__original:
            self.__node_info.add_new_task_sent(node_index)
        else:
            self.__node_info.add_old_task_sent(node_index)

        # Just block
        done = self.context().server_conn.recv()
        serverdone = time()
        assert done == "SERVER_DONE"
        self.context().add_time('server_time', serverdone - sent)

        with self.wrapped_task().lock():
            if self.wrapped_task().is_completed():
                self.context().server_conn.send(False)
                return False
            self.wrapped_task().mark_completed()
            self.context().server_conn.send(True)

        start = time()
        result = self.wrapped_task().task().manager_receive(self.context())
        self.context().add_time('receive', time() - start)
        return result

    def __call__(self):
        self.run()

    def run(self):
        if hasattr(self.wrapped_task().task(), 'manager_prepare'):
            start = time()
            if self.wrapped_task().task().algorithm == 'SCAN_HEADERS':
                self.wrapped_task().task().tempfile = self.wrapped_task().task().manager_prepare()
                if not self.wrapped_task().task().tempfile:
                    raise RuntimeError("Failed to preprocess.")
                    #task.algorithm = 'PREPROCESS_LOCALLY'

            if self.wrapped_task().task().algorithm == 'PREPROCESS_LOCALLY':
                # Signal the client to do preprocessing.
                self.context().server_conn.send('PREPROCESS')
                # Wait for 'done'.
                done = client_conn.recv()
                assert done == 'DONE'
            self.context().add_time('prepare', time() - start)

        try:
            fan = time()
            find_node_result = self.find_available_node()
            self.context().add_time('find_available_node', time() - start)
            if find_node_result is None:
                return

            node_index, server_conn = find_node_result
            self.context().server_conn = server_conn
            self.__task_map.setdefault(self.wrapped_task().client_id(), set()).add(node_index)

            start = time()
            # Create and run worker.
            result = self.process_task(node_index)
            # Did not process it after all.
            if result is None:
                return

            if result:
                self.__node_info.add_tasks_completed(node_index)
            else:
                self.__node_info.add_tasks_failed(node_index)

        finally:
            self.context().add_time('run_task', time() - start)

    def find_available_node(self):
        nodes_processing_task = self.__task_map.get(self.__wrapped_task.client_id(), set())
        first = None
        accepted = False
        rejections = 0
        # Crucial part of the algorithm - ordering of nodes by quality.
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
                # A 'better' node is already working on this task.
                if node_index in nodes_processing_task:
                    return

                if nodes_processing_task:
                    current_best = max([self.completion_ratio(node_index) for node_index in nodes_processing_task])
                    if self.completion_ratio(node_index) <= current_best:
                        # We already have a better node working
                        return

                try:
                    server_conn = Client(address=node)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    continue
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
    def __init__(self, task, client_id):
        self.__client_id = client_id
        self.__task = task
        self.__lock = Lock()
        self.__completed = Value(ctypes.c_bool, False, lock=False)
        self.__nodes_processing = []

    def is_completed(self):
        return self.__completed.value

    def mark_completed(self):
        self.__completed.value = True

    def task(self):
        return self.__task

    def client_id(self):
        return self.__client_id

    def nodes_processing(self):
        return self.__nodes_processing

    def __lt__(self, other):
        return len(self.__nodes_processing) < len(other.nodes_processing())

    def lock(self):
        return self.__lock

class TaskProcessor(Process):
    def __init__(self, nodes, queue, manager):
        self.__queue = queue
        self.__nodes = nodes

        self.__node_info = manager.NodeInfoHolder(len(nodes))

        self.__tasks = {}
        self.__task_map = manager.dict()
        self.__processes = []

        self.__times = manager.dict()

        super(TaskProcessor, self).__init__()

    def run(self):
        self.__prepare_pool = Pool(processes=8)
        self.print_stats()
        while True:
            if self.join_dead_processes():
                self.print_stats()
            self.run_one()

    def run_one(self):
        try:
            task, client_id = self.__queue.get(timeout=0.2)
            wrapped_task = WrapTask(task, client_id)
            client_conn = Client(address=r"\\.\pipe\{}".format(client_id), authkey=None)
            self.__tasks[client_id] = wrapped_task, client_conn
            start = time()
            worker = Worker(wrapped_task, client_conn, self.__times, self.__task_map, self.__nodes, self.__node_info)
            self.__processes.append(worker)
            worker.start()
            self.__times['spawn_worker'] = self.__times.get('spawn_worker', 0) + (time() - start)
        except Empty:
            pass

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
            print('{} - {}'.format(time, times[time]))

task_queue = Queue()



class NodeInfo:
    def __init__(self):
        self._tasks_completed = 0
        self._tasks_failed    = 0
        self._new_tasks_sent  = 0
        self._old_tasks_sent  = 0

class NodeInfoHolder:
    def __init__(self, size):
        self.__nodes = tuple((NodeInfo() for i in range(size)))

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

class BookKeepingManager(SyncManager):
    pass

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

    bookKeepingManager = BookKeepingManager()
    bookKeepingManager.start()

    task_processor = TaskProcessor(nodes, task_queue, bookKeepingManager)
    task_processor.start()

    server = queue_manager.get_server()
    server.serve_forever()
