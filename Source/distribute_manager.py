#! python3.3
from functools import cmp_to_key
from multiprocessing import Process, Pool, cpu_count
from multiprocessing.managers import SyncManager, BaseProxy
from time import sleep, time

from scan_headers import collect_headers
from utils import send_file, send_compressed_file

import configparser
import operator
import os
import pickle
import socket
import sys
import zmq
import zlib

from Messaging import Client as MsgClient

class ContextManagerTimer:
    def __init__(self, callable):
        self.__callable = callable
        self.__start = time()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__callable(time() - self.__start)

class ScopedTimer:
    def __init__(self, callable):
        self.__callable = callable
        self.__start = time()

    def __del__(self):
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
        return ContextManagerTimer(lambda value : self.add_time(name, value))

    def scoped_timer(self, name):
        return ScopedTimer(lambda value : self.add_time(name, value))

class ScanHeaders(Process):
    def __init__(self, port, timer):
        self.__port = port
        self.__timer = timer
        return super().__init__()

    def run(self):
        zmq_ctx = zmq.Context()
        socket = zmq_ctx.socket(zmq.DEALER)
        socket.connect('tcp://localhost:{}'.format(self.__port))

        while True:
            client_id, task = socket.recv_multipart()
            result = self.prepare_task(pickle.loads(task))
            socket.send_multipart([client_id, pickle.dumps(result)])

    def prepare_task(self, task):
        # TODO: This does not belong here. Move this to msvc.py.
        # We would like to avoid scanning system headers here if possible.
        # If we do so, we lose any preprocessor side-effects. We try to
        # hardcode this knowledge here.
        with self.__timer.timeit('prepare'):
            macros = task.preprocessor_info.all_macros
            macros += task.compiler_info.macros()
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


class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_OK = 1
    STATE_WAIT_FOR_PCH_RESPONSE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_PREPROCESS_LOCALLY_START = 4
    STATE_RELAY_PREPROCESSED_FILE = 5
    STATE_WAIT_FOR_SERVER_RESPONSE = 6
    STATE_COLLECT_SERVER_RETCODE_AND_OUTPUT = 7
    STATE_RECEIVE_RESULT_FILE = 8
    STATE_WAIT_FOR_COMPILER_INFO = 9
    STATE_DONE = 10
    
    def __init__(self, task, timer, client_conn, server_conn, preprocess_socket, node_info, node_index, compiler_info):
        self.task = task
        self.timer = timer
        self.client_conn = client_conn
        self.server_conn = server_conn
        self.preprocess_socket = preprocess_socket
        self.node_info = node_info
        self.node_index = node_index
        self.compiler_info = compiler_info

        self.node_info.connection_open(self.node_index)
        self.start_task()

    def __del__(self):
        self.node_info.connection_closed(self.node_index)

    def start_task(self):
        if self.task.compiler_executable in self.compiler_info:
            self.task.compiler_info = self.compiler_info[self.task.compiler_executable]
            self.preprocess_socket.send_multipart([self.client_conn.id, pickle.dumps(self.task)])
            with self.timer.timeit('send'):
                self.server_conn.send_pyobj(self.task)
            self.node_info.add_tasks_sent(self.node_index)
            self.state = self.STATE_WAIT_FOR_OK
        else:
            self.client_conn.send_pyobj("GET_COMPILER_INFO")
            self.state = self.STATE_WAIT_FOR_COMPILER_INFO

    def got_data_from_client(self, msg):
        assert self.state in [self.STATE_RELAY_PREPROCESSED_FILE, self.STATE_WAIT_FOR_COMPILER_INFO]
        if self.state == self.STATE_RELAY_PREPROCESSED_FILE:
            assert self.task.algoritm == 'PREPROCESS_LOCALLY'
            more, data = msg
            self.server_conn.send_pyobj((more, data))
            if not more:
                self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE
        else:
            self.compiler_info[self.task.compiler_executable] = pickle.loads(msg[1])
            self.task.compiler_info = self.compiler_info[self.task.compiler_executable]
            self.preprocess_socket.send_multipart([self.client_conn.id, pickle.dumps(self.task)])
            with self.timer.timeit('send'):
                self.server_conn.send_pyobj(self.task)
            self.node_info.add_tasks_sent(self.node_index)
            self.state = self.STATE_WAIT_FOR_OK
        return False

    def got_data_from_server(self, msg):
        assert self.state != self.STATE_RELAY_PREPROCESSED_FILE
        if self.state == self.STATE_WAIT_FOR_OK:
            task_ok = msg
            assert task_ok == "OK"
            if self.task.algorithm == 'SCAN_HEADERS':
                self.server_conn.send_pyobj('SCAN_HEADERS')
                self.server_conn.send_pyobj('HEADERS_ARCHIVE')
                with self.timer.timeit('send.zip'), open(self.task.tempfile, 'rb') as file:
                    send_file(self.server_conn.send_pyobj, file)
                os.remove(self.task.tempfile)
                self.server_conn.send_pyobj('SOURCE_FILE')
                with self.timer.timeit('send.source'), open(os.path.join(self.task.cwd, self.task.source), 'rb') as cpp:
                    send_compressed_file(self.server_conn.send_pyobj, cpp)
                if self.task.pch_file:
                    self.server_conn.send_pyobj('NEED_PCH_FILE')
                    self.state = self.STATE_WAIT_FOR_PCH_RESPONSE
                else:
                    self.server_timer = self.timer.scoped_timer('server_time')
                    self.average_timer = ScopedTimer(lambda value : self.node_info.add_total_time(self.node_index, value))
                    self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

            elif self.task.algorithm == 'PREPROCESS_LOCALLY':
                self.server_conn.send('PREPROCESS_LOCALLY')
                # Signal the client to do preprocessing.
                self.client_conn.send_pyobj('PREPROCESS')
                self.server_conn.send_pyobj('PREPROCESSED_FILE')
                self.state = self.STATE_RELAY_PREPROCESSED_FILE
            else:
                assert not "Invalid state"

        elif self.state == self.STATE_WAIT_FOR_PCH_RESPONSE:
            response = msg
            if response == "YES":
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_pyobj, pch_file)
            else:
                assert response == "NO"
            self.server_timer = self.timer.scoped_timer('server_time')
            self.average_timer = ScopedTimer(lambda value : self.node_info.add_total_time(self.node_index, value))
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            del self.server_timer
            del self.average_timer
            server_status = msg
            if server_status == "SERVER_FAILED":
                self.state = self.STATE_DONE
                return True
            assert server_status == "SERVER_DONE"
            self.state = self.STATE_COLLECT_SERVER_RETCODE_AND_OUTPUT

        elif self.state == self.STATE_COLLECT_SERVER_RETCODE_AND_OUTPUT:
            self.retcode, self.stdout, self.stderr = msg
            if self.retcode == 0:
                self.output = open(self.task.output, "wb")
                self.output_decompressor = zlib.decompressobj()
                self.state = self.STATE_RECEIVE_RESULT_FILE
            else:
                self.client_conn.send_pyobj('COMPLETED')
                self.client_conn.send_pyobj((self.retcode, self.stdout, self.stderr))
                self.node_info.add_tasks_completed(self.node_index)
                return True

        elif self.state == self.STATE_RECEIVE_RESULT_FILE:
            more, data = msg
            self.output.write(self.output_decompressor.decompress(data))
            if not more:
                self.output.write(self.output_decompressor.flush())
                del self.output_decompressor
                self.output.close()
                del self.output
                self.client_conn.send_pyobj('COMPLETED')
                self.client_conn.send_pyobj((self.retcode, self.stdout, self.stderr))
                self.node_info.add_tasks_completed(self.node_index)
                return True
        return False

class TaskProcessor:
    def __init__(self, nodes, port):
        self.__port = port
        self.__nodes = nodes

        super(TaskProcessor, self).__init__()

    def __find_node(self, nodes, node_info, timer):
        def cmp(lhs, rhs):
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

        with timer.timeit('find_available_node'):
            while True:
                node_indices = list(range(len(nodes)))
                node_indices.sort(key=compare_key)
                for node_index in node_indices:
                    node = nodes[node_index]
                    try:
                        server_conn = MsgClient(zmq_ctx)
                        server_conn.connect('tcp://{}:{}'.format(node[0], node[1]))
                    except Exception:
                        print("Failed to connect to '{}'".format(node))
                        import traceback
                        traceback.print_exc()
                        continue
                    accept = server_conn.recv_pyobj()
                    if accept == "ACCEPT":
                        return node_index, server_conn
                    else:
                        assert accept == "REJECT"
                with timer.timeit("find_available_node.sleeping"):
                    sleep(0.5)

    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            self.socket.send_multipart([self.id] + data)

        def recv(self):
            self.socket.recv_multipart()

        def send_pyobj(self,obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    def run(self):
        zmq_ctx = zmq.Context()
        client_socket = zmq_ctx.socket(zmq.ROUTER)
        client_socket.bind('tcp://*:{}'.format(self.__port))

        preprocess_socket = zmq_ctx.socket(zmq.DEALER)
        preprocess_socket_port = preprocess_socket.bind_to_random_port('tcp://*')

        poller = zmq.Poller()
        poller.register(client_socket, zmq.POLLIN)
        poller.register(preprocess_socket, zmq.POLLIN)

        session_from_server = {}
        session_from_client = {}

        compiler_info = {}

        self.last_time = None
        try:
            with BookKeepingManager() as book_keeper:
                node_info = book_keeper.NodeInfoHolder(len(self.__nodes))
                timer = book_keeper.Timer()

                scan_workers = [ScanHeaders(preprocess_socket_port, timer) for i in range(cpu_count() + 2)]
                for scan_worker in scan_workers:
                    scan_worker.start()

                while True:
                    self.print_stats(node_info, timer.as_dict())
                    sockets = dict(poller.poll(1000))
                    for socket, flags in sockets.items():
                        if flags != zmq.POLLIN:
                            continue

                        if socket is preprocess_socket:
                            client_id, result = preprocess_socket.recv_multipart()
                            assert client_id in session_from_client
                            session = session_from_client[client_id]
                            session.task.tempfile = pickle.loads(result)
                            poller.register(session.server_conn.socket, zmq.POLLIN)

                        elif socket is client_socket:
                            msg = client_socket.recv_multipart()
                            client_id = msg[0]
                            if client_id not in session_from_client:
                                task = pickle.loads(msg[1])
                                node_index, server_conn = self.__find_node(self.__nodes, node_info, timer)
                                client_conn = self.SendProxy(client_socket, client_id)
                                client_conn.send_pyobj("TASK_RECEIVED")
                                session = CompileSession(task, timer, client_conn, server_conn, preprocess_socket, node_info, node_index, compiler_info)
                                session_from_client[client_conn.id] = session
                                session_from_server[server_conn.socket] = session
                            else:
                                session = session_from_client[client_id]
                                server_socket = session.server_conn.socket
                                assert server_socket in session_from_server
                                session_done = session.got_data_from_client(msg)
                                if session_done:
                                    del session_from_client[client_id]
                                    del session_from_server[server_socket]
                                    poller.unregister(server_socket)

                        else:
                            assert socket in session_from_server
                            session = session_from_server[socket]
                            msg = socket.recv_pyobj()
                            client_id = session.client_conn.id
                            assert client_id in session_from_client
                            session_done = session.got_data_from_server(msg)
                            if session_done:
                                del session_from_client[client_id]
                                del session_from_server[socket]
                                poller.unregister(socket)
        finally:
            for scan_worker in scan_workers:
                scan_worker.terminate()

    def print_stats(self, node_info, times):
        current = time()
        if self.last_time and (current - self.last_time < 2):
            return
        self.last_time = current
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:15}:{:5} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Average Time {:<3.2f} Ratio {:<3.2f}\n'
            .format(
                node[0], node[1],
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
        sorted_times.sort(key=operator.itemgetter(1), reverse=True)
        for name, tm, count, average in sorted_times:
            print('{:-<30} Total {:->10.2f} Num {:->5} Average {:->10.2f}'.format(name, tm, count, average))

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

    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    import zmq
    zmq_ctx = zmq.Context()

    try:
        TaskProcessor(nodes, port).run()
    finally:
        print("Shutting down.")
