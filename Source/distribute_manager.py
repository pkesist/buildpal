from queue import PriorityQueue
from multiprocessing import Lock, Pipe, Pool, Process, Queue, current_process
from multiprocessing.connection import Client
from multiprocessing.managers import BaseManager
from time import sleep

import sys
import os
import configparser

class Worker(Process):
    def __init__(self, nodes, wrapped_task):
        self.__wrapped_task = wrapped_task
        self.__nodes = nodes
        super(Worker, self).__init__()

    def run(self):
        first = None
        accepted = False
        rejections = 0
        while not accepted:
            node = self.__wrapped_task.next_node(self.__nodes)
            if not first:
                first = node
            elif node == first:
                # If everyone rejected task.
                sleep(1)
            try:
                conn = Client(address=node)
            except:
                import traceback
                traceback.print_exc()
                print("Connection to '{}:{}' failed. Moving on.".format(node[0], node[1]))
                continue
            conn.send(self.__wrapped_task.task())
            try:
                accepted, has_compiler = conn.recv()
                if not accepted:
                    rejections += 1
                    conn.close()
                else:
                    break
            except IOError:
                pass
        self.__wrapped_task.task().send_receive(conn, self.__wrapped_task.lock(), self.__wrapped_task.endpoint())

class WrapTask:
    def __init__(self, task, endpoint):
        self.__endpoint = endpoint
        self.__task = task
        self.__lock = Lock()
        self.__curr_node = 0

    def next_node(self, nodes):
        tmp = self.__curr_node
        self.__curr_node = (self.__curr_node + 1) % len(nodes)
        return nodes[tmp]

    def task(self):
        return self.__task

    def endpoint(self):
        return self.__endpoint

    def lock(self):
        return self.__lock

class TaskProcessor(Process):
    def __init__(self, nodes, queue):
        self.__queue = queue
        self.__nodes = nodes
        self.__last_node = 0
        super(TaskProcessor, self).__init__()

    def run(self):
        processes = []
        priority_queue = PriorityQueue()
        while True:
            # Join completed processes.
            dead=filter(lambda p : not p.is_alive(), processes)
            processes=[p for p in processes if p not in dead]
            for d in dead:
                d.join()

            # Get new task.
            # If there are no new tasks on queue re-send an old one.
            if not self.__queue.empty() or priority_queue.empty():
                task, endpoint = self.__queue.get()
                priority = 0
                wrapped_task = WrapTask(task, endpoint)
            else:
                priority, wrapped_task = priority_queue.get()
                with wrapped_task.lock():
                    if not wrapped_task.task().complete():
                        priority_queue.put((priority + 1, wrapped_task))

            # Create and run worker.
            worker = Worker(self.__nodes, wrapped_task)
            processes.append(worker)
            worker.start()

task_queue = Queue()

class DistributeManager(BaseManager):
    pass

def queue_task(task, endpoint):
    task_queue.put((task, endpoint))

def get_queue():
    return task_queue


DistributeManager.register('queue_task', callable=queue_task)
DistributeManager.register('get_queue', callable=get_queue)

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

    print("Spawning a manager with id '{}'".format(id))
    print("================")
    print("Build nodes:")
    print("================")
    for node in nodes:
        print('{}:{}'.format(node[0], node[1]))
    print("================")

    server = manager.get_server()
    server.serve_forever()
