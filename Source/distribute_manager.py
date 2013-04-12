from queue import PriorityQueue, Empty
from multiprocessing import Lock, Process, Queue, Value
from multiprocessing.connection import Client
from multiprocessing.managers import BaseManager
from time import sleep, time

import ctypes
import heapq
import sys
import os
import configparser

class Worker(Process):
    def __init__(self, wrapped_task, server_conn, client_conn, index):
        self.__wrapped_task = wrapped_task
        self.__server_conn = server_conn
        self.__client_conn = client_conn
        self.__index = index
        super(Worker, self).__init__()

    def run(self):
        self.__wrapped_task.task().manager_send(
            self.__server_conn,
            self.__client_conn,
            self.__wrapped_task,
            self.__index)

        self.__wrapped_task.task().manager_receive(
            self.__server_conn,
            self.__client_conn,
            self.__wrapped_task,
            self.__index)

class WrapTask:
    def __init__(self, task, endpoint):
        self.__endpoint = endpoint
        self.__task = task
        self.__lock = Lock()
        self.__preprocessed = Value(ctypes.c_bool, False, lock=False)
        self.__completed = Value(ctypes.c_bool, False, lock=False)
        self.__completer = Value(ctypes.c_byte, 0, lock=False)
        self.__nodes_processing = []

    def mark_completed(self, node_index):
        self.__completed.value = True
        self.__completer.value = node_index

    def mark_preprocessed(self):
        self.__preprocessed.value = True

    def is_completed(self):
        return self.__completed.value

    def is_preprocessed(self):
        return self.__preprocessed.value

    def completer(self):
        return self.__completer.value

    def task(self):
        return self.__task

    def endpoint(self):
        return self.__endpoint

    def nodes_processing(self):
        return self.__nodes_processing

    def __lt__(self, other):
        return len(self.__nodes_processing) < len(other.nodes_processing())

    def lock(self):
        return self.__lock

class TaskProcessor(Process):
    def __init__(self, nodes, queue):
        self.__queue = queue
        self.__nodes = nodes
        self.__tasks_completed = {}
        self.__new_tasks_sent = {}
        self.__old_tasks_sent = {}

        self.__tasks = {}
        self.__task_map = {}
        self.__processes = []
        self.__priority_queue = []

        super(TaskProcessor, self).__init__()

    def run(self):
        self.print_stats()
        while True:
            self.join_dead_processes()
            self.run_one()

    def run_one(self):
        try:
            task, endpoint = self.__queue.get(timeout=0.2)
            client_conn = Client(r"\\.\pipe\{}".format(endpoint), b"")
            self.__tasks[endpoint] = WrapTask(task, endpoint), client_conn
            self.__task_map[endpoint] = set()
            self.run_task(endpoint, True)
        except Empty:
            pass
        finally:
            self.process_pq()

    def new_tasks_sent(self, index):
        return self.__new_tasks_sent.get(index, 0)

    def old_tasks_sent(self, index):
        return self.__old_tasks_sent.get(index, 0)

    def tasks_sent(self, index):
        return self.new_tasks_sent(index) + self.old_tasks_sent(index)

    def tasks_completed(self, index):
        return self.__tasks_completed.get(index, 0)

    def completion_ratio(self, index):
        if not self.tasks_sent(index):
            return 1.0
        return self.tasks_completed(index) / self.tasks_sent(index)

    def process_pq(self):
        found_task = False
        while self.__priority_queue:
            stored_time, endpoint = heapq.heappop(self.__priority_queue)
            wrapped_task, client_conn = self.__tasks[endpoint]
            with wrapped_task.lock():
                if wrapped_task.is_completed():
                    del self.__task_map[endpoint]
                    del self.__tasks[endpoint]
                    self.__tasks_completed[wrapped_task.completer()] = \
                        self.tasks_completed(wrapped_task.completer()) + 1
                    self.print_stats()
                    continue
                else:
                    if time() - stored_time < 3:
                        heapq.heappush(self.__priority_queue, (stored_time, endpoint))
                        return
                    found_task = True
                    break
        if not found_task:
            return
        self.run_task(endpoint, False)


    def run_task(self, endpoint, original):
        heapq.heappush(self.__priority_queue, (time(), endpoint))
        find_node_result = self.find_available_node(endpoint)
        if find_node_result is None:
            return

        node_index, server_conn = find_node_result
        self.__task_map[endpoint].add(node_index)

        # Create and run worker.
        if original:
            self.__new_tasks_sent[node_index] = self.new_tasks_sent(node_index) + 1
        else:
            self.__old_tasks_sent[node_index] = self.old_tasks_sent(node_index) + 1
        task, client_conn = self.__tasks[endpoint]
        worker = Worker(task, server_conn, client_conn, node_index)
        self.__processes.append(worker)
        worker.start()


    def join_dead_processes(self):
        dead=filter(lambda p : not p.is_alive(), self.__processes)
        self.__processes=[p for p in self.__processes if p not in dead]
        for d in dead:
            d.join()

    def print_stats(self):
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:15}:{:5} - New sent {:<3} Old sent {:<3} '
                'Completed {:<3} Ratio {:<3}\n'.format(node[0], node[1],
                self.new_tasks_sent(index), self.old_tasks_sent(index),
                self.tasks_completed(index), self.completion_ratio(index)))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))


    def find_available_node(self, endpoint):
        wrapped_task, client_conn = self.__tasks[endpoint]
        nodes_processing_task = self.__task_map[endpoint]
        first = None
        accepted = False
        rejections = 0
        best_nodes = [(self.completion_ratio(index), -self.tasks_completed(index), -self.tasks_sent(index),
            self.__nodes[index], index) for index in range(len(self.__nodes))
            if not index in nodes_processing_task]
        if not best_nodes:
            return
        best_nodes.sort(reverse=True)
        while not accepted:
            for entry in best_nodes:
                ignore, ignore, ignore, node, node_index = entry
                if not first:
                    first = node
                elif node == first:
                    # If everyone rejected task.
                    if nodes_processing_task:
                        return
                    else:
                        sleep(1)
                if node_index in nodes_processing_task:
                    return

                if nodes_processing_task:
                    current_best = max([self.completion_ratio(node_index) for node_index in nodes_processing_task])
                    if self.completion_ratio(node_index) <= current_best:
                        # We already have a better node working
                        return

                try:
                    conn = Client(address=node)
                except:
                    import traceback
                    traceback.print_exc()
                    continue
                conn.send(wrapped_task.task())
                try:
                    accepted, has_compiler = conn.recv()
                    if not accepted:
                        rejections += 1
                        conn.close()
                    else:
                        break
                except IOError:
                    pass
            return node_index, conn



task_queue = Queue()

class DistributeManager(BaseManager):
    pass

def queue_task(task, endpoint):
    task_queue.put((task, endpoint))

DistributeManager.register('queue_task', callable=queue_task)

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
   
    manager = DistributeManager(r"\\.\pipe\{}".format(id), b"")

    task_processor = TaskProcessor(nodes, task_queue)
    task_processor.start()

    server = manager.get_server()
    server.serve_forever()
