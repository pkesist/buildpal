#! python3
from queue import PriorityQueue, Empty
from multiprocessing import Lock, Manager, Process, Pool, Queue, Value, RawValue
from multiprocessing.connection import Client
from multiprocessing.managers import BaseManager
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
    def __init__(self, wrapped_task, server_conn, client_conn, node_info, original, global_dict, times):
        ctx = Context()
        ctx.server_conn = server_conn
        ctx.client_conn = client_conn
        ctx.global_dict = global_dict
        ctx.times       = times

        self.__ctx = ctx

        self.__wrapped_task = wrapped_task
        self.__node_info = node_info
        self.__original = original
        super(Worker, self).__init__()

    def wrapped_task(self): return self.__wrapped_task

    def context(self):
        return self.__ctx

    def process_task(self):
        start = time()
        self.wrapped_task().task().manager_send(self.context())
        sent = time()
        self.context().add_time('send', sent - start)

        if self.__original:
            self.__node_info.tasks_sent_new += 1
        else:
            self.__node_info.tasks_sent_old += 1

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


    def run(self):
        result = self.process_task()
        # Did not process it after all.
        if result is None:
            return

        if result:
            self.__node_info.tasks_completed += 1
        else:
            self.__node_info.tasks_failed += 1


class NodeInfo(ctypes.Structure):
    _fields_ = [
        ('index'          , ctypes.c_uint),
        ('tasks_completed', ctypes.c_uint), 
        ('tasks_failed'   , ctypes.c_uint), 
        ('tasks_sent_new' , ctypes.c_uint),
        ('tasks_sent_old' , ctypes.c_uint)]


class WrapTask:
    def __init__(self, task, endpoint):
        self.__endpoint = endpoint
        self.__task = task
        self.__lock = Lock()
        self.__prepared = Value(ctypes.c_bool, False, lock=False)
        self.__completed = Value(ctypes.c_bool, False, lock=False)
        self.__nodes_processing = []

    def is_completed(self):
        return self.__completed.value

    def is_prepared(self):
        return self.__prepared.value

    def mark_completed(self):
        self.__completed.value = True

    def mark_prepared(self):
        self.__prepared.value = True

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

def prepare_task(task):
    return task.manager_prepare()

class TaskProcessor(Process):
    def __init__(self, nodes, queue, global_dict, times):
        self.__queue = queue
        self.__nodes = nodes
        self.__node_info = [Value(NodeInfo, index, 0, 0, 0, 0) for index in range(len(nodes))]

        self.__tasks = {}
        self.__task_map = {}
        self.__processes = []
        self.__priority_queue = []

        self.__global_dict = global_dict
        self.__times = times
        self.__prepared = 0

        super(TaskProcessor, self).__init__()

    def run(self):
        self.__prepare_pool = Pool(processes=4)
        self.print_stats()
        while True:
            if self.join_dead_processes():
                self.print_stats()
            self.run_one()

    def run_one(self):
        try:
            task, endpoint = self.__queue.get(timeout=0.2)
            client_conn = Client(r"\\.\pipe\{}".format(endpoint), b"")

            if hasattr(task, 'manager_prepare'):
                start = time()
                if task.algorithm == 'SCAN_HEADERS':
                    task.tempfile = self.__prepare_pool.apply(prepare_task, args=(task,))
                    if not task.tempfile:
                        raise RuntimeError("Failed to preprocess.")
                        #task.algorithm = 'PREPROCESS_LOCALLY'

                if task.algorithm == 'PREPROCESS_LOCALLY':
                    # Signal the client to do preprocessing.
                    client_conn.send('PREPROCESS')
                    # Wait for 'done'.
                    done = client_conn.recv()
                    assert done == 'DONE'

                #if not task.manager_prepare(client_conn):
                #    raise RuntimeError("Failed to prepare task.")
                self.__prepared += 1
                self.__times['prepare'] = self.__times.get('prepare', 0) + (time() - start)

            self.__tasks[endpoint] = WrapTask(task, endpoint), client_conn
            self.__task_map[endpoint] = set()
            self.run_task(endpoint, True)
        except Empty:
            pass
        finally:
            self.process_pq()

    def new_tasks_sent(self, index):
        return self.__node_info[index].tasks_sent_new

    def old_tasks_sent(self, index):
        return self.__node_info[index].tasks_sent_old

    def tasks_sent(self, index):
        return self.new_tasks_sent(index) + self.old_tasks_sent(index)

    def tasks_completed(self, index):
        return self.__node_info[index].tasks_completed

    def tasks_failed(self, index):
        return self.__node_info[index].tasks_failed

    def tasks_processing(self, index):
        return self.tasks_sent(index) - self.tasks_completed(index) - self.tasks_failed(index)

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
                    continue
                else:
                    if time() - stored_time < 5:
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
        task, client_conn = self.__tasks[endpoint]
        worker = Worker(task, server_conn, client_conn, self.__node_info[node_index], original, self.__global_dict, self.__times)
        self.__processes.append(worker)
        worker.start()

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
                'Completed {:<3} Failed {:<3} Running {:<3} Ratio {:<3}\n'.format(node[0],
                node[1], self.new_tasks_sent(index), self.old_tasks_sent(index),
                self.tasks_completed(index), self.tasks_failed(index),
                self.tasks_processing(index), self.completion_ratio(index)))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        times = self.__times._getvalue()
        if self.__prepared:
            print("Preprocessing #{}, average time {}s".format(self.__prepared, times.get('prepare', 0)/self.__prepared))
        for time in times:
            print('{} - {}'.format(time, times[time]))

    def find_available_node(self, endpoint):
        wrapped_task, client_conn = self.__tasks[endpoint]
        nodes_processing_task = self.__task_map[endpoint]
        first = None
        accepted = False
        rejections = 0
        # Crucial part of the algorithm - ordering of nodes by quality.
        best_nodes = [(
             self.tasks_failed(index),
             self.tasks_processing(index),
             self.completion_ratio(index),
             self.__nodes[index], index)
             for index in range(len(self.__nodes))
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
                # A 'better' node is already working on this task.
                if node_index in nodes_processing_task:
                    return

                if nodes_processing_task:
                    current_best = max([self.completion_ratio(node_index) for node_index in nodes_processing_task])
                    if self.completion_ratio(node_index) <= current_best:
                        # We already have a better node working
                        return

                try:
                    conn = Client(address=node)
                except Exception:
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
                        return node_index, conn
                except IOError:
                    pass



task_queue = Queue()

class DistributeManager(BaseManager):
    pass

def queue_task(task, endpoint):
    task_queue.put((task, endpoint))

def get_task(*args, **kwargs):
    return task_queue.get(*args, **kwargs)


DistributeManager.register('queue_task', callable=queue_task)
DistributeManager.register('get_task', callable=get_task)

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

    
    local_manager = Manager()

    task_processor = TaskProcessor(nodes, task_queue, local_manager.dict(), local_manager.dict())
    task_processor.start()

    server = manager.get_server()
    server.serve_forever()
