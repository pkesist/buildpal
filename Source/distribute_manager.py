#! python3.3
from functools import cmp_to_key
from queue import Empty
from multiprocessing import Lock, Process, Pool, Queue
from multiprocessing.managers import SyncManager, BaseProxy
from concurrent.futures import ThreadPoolExecutor
from threading import Lock as ThreadLock
from time import sleep, time

from scan_headers import collect_headers
from utils import send_file, receive_compressed_file, send_compressed_file, relay_file

import configparser
import operator
import os
import pickle
import socket
import sys
import zmq

from Messaging import Client as MsgClient

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

def set_zmq_ctx():
    global zmq_ctx
    zmq_ctx = zmq.Context()

def get_zmq_ctx():
    global zmq_ctx
    return zmq_ctx

class ScanHeaders(Process):
    def __init__(self, port, workers):
        self.__port = port
        self.__workers = workers
        return super().__init__()

    def run(self):
        zmq_ctx = zmq.Context()
        executor = ThreadPoolExecutor(max_workers=self.__workers)
        self.socket = zmq_ctx.socket(zmq.DEALER)
        self.socket.connect('tcp://localhost:{}'.format(self.__port))

        while True:
            client_id, task = self.socket.recv_multipart()
            task = pickle.loads(task)
            future = executor.submit(self.prepare_task, task)
            future.add_done_callback(lambda future : self.task_done(client_id, future))

    def task_done(self, client_id, future):
        assert future.done()
        result = future.result()
        self.socket.send_multipart([client_id, pickle.dumps(result)])

    def prepare_task(self, task):
        # TODO: This does not belong here. Move this to msvc.py.
        # We would like to avoid scanning system headers here if possible.
        # If we do so, we lose any preprocessor side-effects. We try to
        # hardcode this knowledge here.
        macros = task.preprocessor_info.all_macros
        if '_DEBUG' in macros:
            if not any(('_SECURE_SCL' in x for x in macros)):
                macros.append('_SECURE_SCL=1')
            if not any(('_HAS_ITERATOR_DEBUGGING' in x for x in macros)):
                macros.append('_HAS_ITERATOR_DEBUGGING=1')

        if task.algorithm == 'SCAN_HEADERS':
            return collect_headers(os.path.join(task.cwd, task.source),
                task.preprocessor_info.includes, [], macros,
                [task.pch_header] if task.pch_header else [])

        else:
            raise Exception("Invalid algorithm.")


class CompileWorker:
    def __init__(self, task, timer, done_port, preprocess_port):
        self.task = task
        self.timer = timer
        self.done_port = done_port
        self.preprocess_port = preprocess_port

    def __prepare_task(self, zmq_ctx):
        if self.task.algorithm != 'SCAN_HEADERS':
            return None

        socket = zmq_ctx.socket(zmq.DEALER)
        socket.connect('tcp://localhost:{}'.format(self.preprocess_port))
        socket.send_pyobj(self.task)
        return socket

    def __find_node(self, nodes, node_info):
        def cmp(lhs, rhs):
            #lhs_tasks_processing = node_info.tasks_processing(lhs)
            #rhs_tasks_processing = node_info.tasks_processing(rhs)
            lhs_tasks_processing = node_info.connections(lhs)
            rhs_tasks_processing = node_info.connections(rhs)
            lhs_average_time = node_info.average_time(lhs)
            rhs_average_time = node_info.average_time(rhs)
            if lhs_average_time == 0 and rhs_average_time == 0:
                return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
            if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
                return -1 if lhs_average_time < rhs_average_time else 1
            return -1 if lhs_tasks_processing * lhs_average_time <= rhs_tasks_processing * rhs_average_time else 1
        compare_key = cmp_to_key(cmp)

        with self.timer.timeit('find_available_node'):
            while True:
                node_index = min(range(len(nodes)), key=compare_key)
                node = nodes[node_index]
                try:
                    client = MsgClient(zmq_ctx)
                    client.connect('tcp://{}:{}'.format(node[0], node[1]))
                except Exception:
                    print("Failed to connect to '{}'".format(node))
                    import traceback
                    traceback.print_exc()
                    return None
                accept = client.recv_pyobj()
                if accept == "ACCEPT":
                    return node_index, client
                else:
                    assert accept == "REJECT"
                    with self.timer.timeit('find_available_node.sleeping'):
                        sleep(1)

    class SendProxy:
        def __init__(self, port, id, zmq_ctx):
            self.socket = zmq_ctx.socket(zmq.DEALER)
            self.id = id
            self.socket.connect('tcp://localhost:{}'.format(port))

        def send(self, data):
            self.socket.send_multipart([self.id] + data)

        def recv(self):
            self.socket.recv_multipart()

        def send_pyobj(self,obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    def __call__(self, client_id, nodes, node_info):
        try:
            zmq_ctx = zmq.Context()
            client_conn = self.SendProxy(self.done_port, client_id, zmq_ctx)
            self.prepare_socket = self.__prepare_task(zmq_ctx)
            node_index, server_conn = self.__find_node(nodes, node_info)

            try:
                node_info.connection_open(node_index)
                node_info.add_tasks_sent(node_index)
                with self.timer.timeit('send'):
                    server_conn.send_pyobj(self.task)
                task_ok = server_conn.recv_pyobj()
                assert task_ok == 'OK'
                self.__send(client_conn, server_conn)

                # Just block
                with self.timer.timeit('server_time'), ScopedTimer(lambda value : node_info.add_total_time(node_index, value)):
                    server_status = server_conn.recv_pyobj()
                    if server_status == "SERVER_FAILED":
                        return None

                assert server_status == "SERVER_DONE"
                with self.timer.timeit('receive'):
                    self.__recv(client_conn, server_conn)
                    node_info.add_tasks_completed(node_index)
            except:
                import traceback
                traceback.print_exc()
            finally:
                node_info.connection_closed(node_index)
        except Exception:
            import traceback
            traceback.print_exc()

    def __send(self, client_conn, server_conn):
        if self.task.algorithm == 'SCAN_HEADERS':
            server_conn.send_pyobj('SCAN_HEADERS')
            server_conn.send_pyobj('ZIP_FILE')
            with self.timer.timeit('prepare_result'):
                tempfile = self.prepare_socket.recv_pyobj()
            assert tempfile
            with self.timer.timeit('send.zip'), open(tempfile, 'rb') as file:
                send_file(server_conn.send_pyobj, file)
            server_conn.send_pyobj('SOURCE_FILE')
            with self.timer.timeit('send.source'), open(os.path.join(self.task.cwd, self.task.source), 'rb') as cpp:
                send_compressed_file(server_conn.send_pyobj, cpp)
            if self.task.pch_file:
                server_conn.send_pyobj('NEED_PCH_FILE')
                response = server_conn.recv_pyobj()
                if response == "YES":
                    with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                        send_compressed_file(server_conn.send_pyobj, pch_file)
                else:
                    assert response == "NO"

        if self.task.algorithm == 'PREPROCESS_LOCALLY':
            server_conn.send('PREPROCESS_LOCALLY')
            # Signal the client to do preprocessing.
            client_conn.send_pyobj('PREPROCESS')
            server_conn.send_pyobj('PREPROCESSED_FILE')
            relay_file(client_conn.recv_pyobj, server_conn.send_pyobj)

    def __recv(self, client_conn, server_conn):
        with self.timer.timeit("receive.server"):
            retcode, stdout, stderr = server_conn.recv_pyobj()
        if retcode == 0:
            length = 0
            more = True
            with self.timer.timeit("receive.object"), open(self.task.output, "wb") as file:
                receive_compressed_file(server_conn.recv_pyobj, file)
        with self.timer.timeit("receive.client"):
            client_conn.send_pyobj('COMPLETED')
            client_conn.send_pyobj((retcode, stdout, stderr))

class TaskProcessor:
    def __init__(self, nodes, max_processes, port):
        self.__port = port
        self.__nodes = nodes
        self.__max_processes = max_processes

        super(TaskProcessor, self).__init__()

    def run(self):
        zmq_ctx = zmq.Context()
        socket = zmq_ctx.socket(zmq.ROUTER)
        socket.bind('tcp://*:{}'.format(self.__port))

        done_socket = zmq_ctx.socket(zmq.DEALER)
        done_port = done_socket.bind_to_random_port('tcp://*')
        
        preprocess_worker_socket = zmq_ctx.socket(zmq.DEALER)
        preprocess_worker_port = preprocess_worker_socket.bind_to_random_port('tcp://*')

        preprocess_socket = zmq_ctx.socket(zmq.ROUTER)
        preprocess_socket_port = preprocess_socket.bind_to_random_port('tcp://*')

        scanHeaders = ScanHeaders(preprocess_worker_port, 32)
        scanHeaders.start()

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        poller.register(done_socket, zmq.POLLIN)
        poller.register(preprocess_worker_socket, zmq.POLLIN)
        poller.register(preprocess_socket, zmq.POLLIN)

        try:
            with BookKeepingManager() as book_keeper, \
                BookKeepingManager() as preparer, \
                Pool(processes=self.__max_processes, initializer=set_zmq_ctx, initargs=()) as compile_pool:
                node_info = book_keeper.NodeInfoHolder(len(self.__nodes))
                timer = book_keeper.Timer()
                while True:
                    self.print_stats(node_info, timer.as_dict())
                    sockets = dict(poller.poll(1000))
                    if sockets.get(socket) == zmq.POLLIN:
                        client_id, task = socket.recv_multipart()
                        task = pickle.loads(task)
                        socket.send_multipart([client_id, pickle.dumps("TASK_RECEIVED")])
                        compile_pool.apply_async(CompileWorker(task, timer, done_port, preprocess_socket_port), args=(client_id, self.__nodes, node_info))

                    if sockets.get(done_socket) == zmq.POLLIN:
                        msg = done_socket.recv_multipart()
                        socket.send_multipart(msg)

                    if sockets.get(preprocess_worker_socket) == zmq.POLLIN:
                        msg = preprocess_worker_socket.recv_multipart()
                        preprocess_socket.send_multipart(msg)

                    if sockets.get(preprocess_socket) == zmq.POLLIN:
                        msg = preprocess_socket.recv_multipart()
                        preprocess_worker_socket.send_multipart(msg)
        finally:
            scanHeaders.terminate()

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

class BookKeepingManager(SyncManager):
    pass

BookKeepingManager.register('Timer', Timer, TimerProxy)
BookKeepingManager.register('NodeInfoHolder', NodeInfoHolder)

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

    port = config.get(manager_section, 'port')
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
   
    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    import zmq
    zmq_ctx = zmq.Context()

    try:
        TaskProcessor(nodes, max_processes, port).run()
    finally:
        print("Shutting down.")
