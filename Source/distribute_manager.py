#! python3.3
from cmdline_processing import *
from functools import cmp_to_key
from multiprocessing import Process, cpu_count
from struct import pack
from time import sleep, time
from msvc import MSVCWrapper
from subprocess import list2cmdline

from scan_headers import collect_headers
from utils import send_file, send_compressed_file, bind_to_random_port, SimpleTimer

import configparser
import io
import operator
import os
import pickle
import socket
import sys
import zlib
import zmq

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

    def stop(self):
        self.__callable(time() - self.__start)

class Timer:
    def __init__(self):
        self.__times = {}

    def add_time(self, type, value):
        current = self.__times.get(type, (0, 0))
        self.__times[type] = (current[0] + value, current[1] + 1)

    def as_dict(self):
        return self.__times

    def scoped_timer(self, name):
        return ScopedTimer(lambda value : self.add_time(name, value))

    def timeit(self, name):
        return ContextManagerTimer(lambda value : self.add_time(name, value))

class ScanHeaders(Process):
    def __init__(self, port, timer, nodes):
        self.__port = port
        self.__timer = timer
        self.__nodes = nodes
        return super().__init__()

    def run(self):
        zmq_ctx = zmq.Context()
        socket = zmq_ctx.socket(zmq.DEALER)
        socket.connect('tcp://localhost:{}'.format(self.__port))
        nodes = {}

        while True:
            server_id, task, node_index = socket.recv_multipart()
            node_index = pickle.loads(node_index)
            timer = SimpleTimer()
            buffer = self.prepare_task(pickle.loads(task))
            if node_index not in nodes:
                server_sock = zmq_ctx.socket(zmq.DEALER)
                server_sock.connect(self.__nodes[node_index])
                nodes[node_index] = server_sock
            nodes[node_index].send_multipart([b'DATA_FOR_SESSION',
                                             server_id, b'TASK_FILES',
                                             buffer.read(),
                                             pickle.dumps(timer.get())],
                                             copy=False)

    def prepare_task(self, task):
        # FIXME: This does not belong here. Move this to msvc.py.
        # We would like to avoid scanning system headers here if possible.
        # If we do so, we lose any preprocessor side-effects. We try to
        # hardcode this knowledge here.
        macros = task['macros']
        if '_DEBUG' in macros:
            if not any(('_SECURE_SCL' in x for x in macros)):
                macros.append('_SECURE_SCL=1')
            if not any(('_HAS_ITERATOR_DEBUGGING' in x for x in macros)):
                macros.append('_HAS_ITERATOR_DEBUGGING=1')
        # FIXME:
        # Usually we don't need sysincludes and including them is really slow.
        # See what to do about this.
        task['sysincludes'] = []
        return collect_headers(task['cwd'], task['source'],
            task['includes'], task['sysincludes'], macros,
            [task['pch_header']] if task['pch_header'] else [])

class OptionValues:
    def __init__(self, values):
        self.__values = values

    def free_options(self):
        return (token for token in self.__values if type(token.option) == FreeOption)

    def filter_options(self, filter):
        if type(filter) == type and issubclass(filter, Category):
            return (token for token in self.__values
                if type(token.option) == CompilerOption and
                token.option.test_category(filter))
        elif isinstance(filter, CompilerOption):
            return (token for token in self.__values
                if token.option.name() == filter.name())
        elif isinstance(filter, str):
            return (token for token in self.__values
                if token.option.name() == filter)
        raise RuntimeError("Unknown option filter.")

    def all(self):
        return self.__values


class TaskCreator:
    def __init__(self, compiler_wrapper, executable, cwd, sysincludes, command,
                 client_conn, timer):
        self.__compiler = compiler_wrapper
        self.__executable = executable
        self.__sysincludes = sysincludes.split(';')
        self.__client_conn = client_conn
        with timer.timeit('parse_options'):
            self.__option_values = OptionValues(list(compiler_wrapper.parse_options(cwd, command[1:])))
        self.__cwd = cwd

    def executable(self):
        return self.__executable

    def option_values(self):
        return self.__option_values

    def input_files(self):
        return (input.make_str() for input in self.__option_values.free_options())

    def build_local(self):
        return bool(list(self.option_values().filter_options(BuildLocalCategory)))

    def create_tasks(self):
        # See if user specified an explicit name for the object file.
        output = list(self.option_values().filter_options(self.__compiler.object_name_option()))
        if output:
            output = output[-1].val
        sources = [input for input in self.input_files() if self.__compiler.requires_preprocessing(input)]
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__compiler.object_name_option.esc(), self.__compiler.object_name_option.name()))

        compile_call, builtin_macros = self.__compiler.create_call(self.executable(), self.option_values())

        includes = [os.path.join(self.__cwd, token.val) for token in self.option_values().filter_options(self.__compiler.include_option())]
        macros = [token.val for token in self.option_values().filter_options(self.__compiler.define_option())]

        pch_header = list(self.option_values().filter_options(self.__compiler.use_pch_option()))
        if pch_header:
            assert len(pch_header) == 1
            pch_header = pch_header[0].val
            pch_file = list(self.option_values().filter_options(self.__compiler.pch_file_option()))
            assert len(pch_file) <= 1
            if pch_file:
                pch_file = pch_file[0].val
            else:
                pch_file = os.path.splitext(pch_header)[0] + '.pch'
            pch_file = os.path.join(self.__cwd, pch_file)
            if not os.path.exists(pch_file):
                raise Exception("PCH file '{}' does not exist.".format(pch_file))
            pch_file = os.path.join(self.__cwd, pch_file)
            pch_file_stat = os.stat(pch_file)
            pch_file = (pch_file, pch_file_stat.st_size, pch_file_stat.st_mtime)
        else:
            pch_header = None
            pch_file = None

        class Task:
            pass

        def create_task(source):
            if os.path.isabs(source):
                source = os.path.relpath(source, self.__cwd)

            task = Task()
            task.__dict__.update(
            {
                'server_task_info' : {
                    'call' : compile_call,
                    'source' : source,
                    'pch_file' : pch_file,
                },
                'preprocess_task_info' : {
                    'cwd' : self.__cwd,
                    'source' : source,
                    'macros' : macros + builtin_macros,
                    'includes' : includes,
                    'sysincludes' : self.__sysincludes,
                    'pch_header' : pch_header
                },
                'output' : os.path.join(self.__cwd, output or os.path.splitext(source)[0] + '.obj'),
                'pch_file' : pch_file,
                'source' : source,
            })
            return task
        return [create_task(source) for source in sources]

    def should_invoke_linker(self):
        return self.__compiler.compile_no_link_option() not in [token.option for token in self.option_values()]

    def postprocess(self):
        if not self.should_invoke_linker():
            return False, None

        print("Linking...")
        objects = {}
        for task in self.tasks:
            objects[task.source] = task.output

        call = [self.executable()]
        call.extend(o.make_str() for o in
            self.option_values().filter_options(LinkingCategory))
        for input in self.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        return True, subprocess.call(call)

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_OK = 1
    STATE_WAIT_FOR_PCH_RESPONSE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 4
    STATE_RECEIVE_RESULT_FILE = 5
    STATE_POSTPROCESS = 6
    STATE_WAIT_FOR_SESSION_DONE = 7
    STATE_WAIT_FOR_SEND_TAR_DONE = 9999

    def __init__(self, compiler, executable, cwd, sysincludes, command, timer,
        client_conn, server_conn, preprocess_socket, node_info, compiler_info):

        self.timer = timer
        self.client_conn = client_conn
        self.server_conn = server_conn
        self.preprocess_socket = preprocess_socket
        self.node_info = node_info
        self.compiler_info = compiler_info
        self.executable = executable

        assert compiler == 'msvc'
        self.compiler = MSVCWrapper()

        self.create_tasks(self.compiler, cwd, sysincludes, command)

    def create_tasks(self, compiler_wrapper, cwd, sysincludes, command):
        ctx = TaskCreator(compiler_wrapper, self.executable, cwd, sysincludes,
                          command, self.client_conn, self.timer)
        if ctx.build_local():
            call = [ctx.executable()]
            call.extend(option.make_str() for option in ctx.option_values().all())
            self.client_conn.send([b'EXECUTE_AND_EXIT\x00' + list2cmdline(call).encode() + b'\x00\x01'])
        else:
            self.tasks = ctx.create_tasks()
            self.task_index = 0
            self.start_task()

    @property
    def task(self):
        return self.tasks[self.task_index]

    def next_task(self):
        if self.task_index >= len(self.tasks) - 1:
            return False
        self.task_index += 1
        return True

    def start_task(self):
        if self.executable in self.compiler_info:
            self.task.compiler_info = self.compiler_info[self.executable]
            self.task.server_task_info['compiler_info'] = self.task.compiler_info
            self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
            server_id = self.server_conn.getsockopt(zmq.IDENTITY)
            assert server_id
            self.average_timer = SimpleTimer()
            self.preprocess_socket.send_multipart([server_id,
                pickle.dumps(self.task.preprocess_task_info),
                pickle.dumps(self.node_info.index())], copy=False)
            with self.timer.timeit('send'):
                self.server_conn.send_pyobj(self.task.server_task_info)
            self.node_info.add_tasks_sent()
            self.state = self.STATE_WAIT_FOR_OK
        else:
            self.test_source = self.compiler.prepare_test_source(self.executable)
            self.client_conn.send([b'EXECUTE_GET_OUTPUT', list2cmdline(self.test_source.command()).encode()])
            self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    def got_data_from_client(self, msg):
        assert self.state in [self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT]
        del self.test_source
        retcode = int(msg[0])
        stdout = msg[1]
        stderr = msg[2]
        info = self.compiler.compiler_info(self.executable, stdout, stderr)
        self.compiler_info[self.executable] = info
        self.task.compiler_info = self.compiler_info[self.executable]
        self.task.server_task_info['compiler_info'] = self.task.compiler_info
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
        server_id = self.server_conn.getsockopt(zmq.IDENTITY)
        assert server_id
        self.average_timer = SimpleTimer()
        self.preprocess_socket.send_multipart([server_id,
            pickle.dumps(self.task.preprocess_task_info),
            pickle.dumps(self.node_info.index())], copy=False)
        with self.timer.timeit('send'):
            self.server_conn.send_pyobj(self.task.server_task_info)
        self.node_info.add_tasks_sent()
        self.state = self.STATE_WAIT_FOR_OK

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_OK:
            task_ok = msg[0]
            assert msg[0] == b'OK'
            if self.task.pch_file:
                self.server_conn.send(b'NEED_PCH_FILE')
                self.state = self.STATE_WAIT_FOR_PCH_RESPONSE
            else:
                self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_PCH_RESPONSE:
            response = msg[0]
            if response == b'YES':
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_multipart, pch_file, copy=False)
            else:
                assert response == b'NO'
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_time = self.average_timer.get()
            del self.average_timer
            self.timer.add_time('server_time', server_time)
            self.node_info.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.client_conn.send([b'EXIT', b'-1'])
                self.state = self.STATE_WAIT_FOR_SESSION_DONE
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, server_times = pickle.loads(msg[1])
                for name, duration in server_times.items():
                    self.timer.add_time("server." + name, duration)
                if self.retcode == 0:
                    self.output = open(self.task.output, "wb")
                    self.output_decompressor = zlib.decompressobj()
                    self.state = self.STATE_RECEIVE_RESULT_FILE
                    self.receive_result_time = SimpleTimer()
                else:
                    self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                    self.node_info.add_tasks_completed()
                    self.state = self.STATE_WAIT_FOR_SESSION_DONE

        elif self.state == self.STATE_RECEIVE_RESULT_FILE:
            more, data = msg
            self.output.write(self.output_decompressor.decompress(data))
            if more == b'\x00':
                self.output.write(self.output_decompressor.flush())
                del self.output_decompressor
                self.timer.add_time('receive_result', self.receive_result_time.get())
                del self.receive_result_time
                self.output.close()
                del self.output
                self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                self.node_info.add_tasks_completed()
                if not self.next_task():
                    self.state = self.STATE_WAIT_FOR_SESSION_DONE
                else:
                    self.start_task()
        elif self.state == self.STATE_WAIT_FOR_SESSION_DONE:
            assert msg[0] == b'SESSION_DESTROYED'
            return True
        return False

class TaskProcessor:
    def __init__(self, nodes, port):
        self.__port = port
        self.__nodes = nodes
        self.__unique_id = 0

        super(TaskProcessor, self).__init__()

    def set_unique_id(self, socket):
        socket.setsockopt(zmq.IDENTITY, b'A' + pack('>I', self.__unique_id))
        self.__unique_id += 1

    def best_node(self, node_info):
        def cmp(lhs, rhs):
            lhs_tasks_processing = node_info[lhs].tasks_processing()
            rhs_tasks_processing = node_info[rhs].tasks_processing()
            lhs_time_per_task = node_info[lhs].average_task_time()
            rhs_time_per_task = node_info[rhs].average_task_time()
            if lhs_time_per_task == 0 and rhs_time_per_task == 0:
                return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
            if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
                return -1 if lhs_time_per_task < rhs_time_per_task else 1
            # In case we don't yet have average time per task for a node, do
            # not allow that node to be flooded.
            if lhs_time_per_task == 0 and lhs_tasks_processing >= 5:
                return 1
            return -1 if lhs_tasks_processing * lhs_time_per_task <= rhs_tasks_processing * rhs_time_per_task else 1
        compare_key = cmp_to_key(cmp)

        return min(range(len(self.__nodes)), key=compare_key)

    def connect_to_node(self, zmq_ctx, node_index, recycled_connections):
        recycled = recycled_connections.get(node_index)
        if recycled:
            socket = recycled[0]
            del recycled[0]
        else:
            node = self.__nodes[node_index]
            try:
                socket = zmq_ctx.socket(zmq.DEALER)
                self.set_unique_id(socket)
                socket.connect(node)
            except Exception:
                print("Failed to connect to '{}'".format(node))
                import traceback
                traceback.print_exc()
                return None
        socket.send(b'CREATE_SESSION')
        return socket

    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            self.socket.send_multipart([self.id, b'\x00'.join(data) + b'\x00\x01'], copy=False)

        def recv(self):
            return self.socket.recv_multipart()

        def send_pyobj(self, obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    def run(self):
        zmq_ctx = zmq.Context()
        client_socket = zmq_ctx.socket(zmq.STREAM)
        client_socket.bind('tcp://*:{}'.format(self.__port))

        preprocess_socket = zmq_ctx.socket(zmq.DEALER)
        preprocess_socket_port = bind_to_random_port(preprocess_socket)

        registered_sockets = set()
        poller = zmq.Poller()

        def register_socket(socket):
            assert socket not in registered_sockets
            poller.register(socket, zmq.POLLIN)
            registered_sockets.add(socket)

        def unregister_socket(socket):
            assert socket in registered_sockets
            registered_sockets.remove(socket)
            poller.unregister(socket)

        register_socket(client_socket)

        compiler_info = {}

        self.last_time = None

        timer = Timer()

        node_info = [NodeInfo(x) for x in range(len(self.__nodes))]

        scan_workers = [ScanHeaders(preprocess_socket_port, timer, self.__nodes) for i in range(cpu_count() * 2)]
        for scan_worker in scan_workers:
            scan_worker.start()

        connections_per_node = 4
        nodes_requested = {}

        # Connections to be re-used.
        recycled_connections = {}

        # Server socket to session mapping.
        session_from_server = {}

        # Client id to session mapping.
        session_from_client = {}

        # Contains nodes which were contacted, but have not yet responded.
        # Value is node_index which is used in local statistics.
        nodes_contacted = {}

        # Contains nodes which responded, but did not yet send whether they
        # accept a task. Value is same as in nodes_contacted.
        node_ids = {}

        # Nodes waiting for a client.
        nodes_waiting = {}

        # Clients waiting for a node.
        clients_waiting = []

        try:
            while True:
                self.print_stats(node_info, timer, recycled_connections)
                for node_index in range(len(node_info)):
                    for x in range(connections_per_node - nodes_requested.get(node_index, 0) - len(nodes_waiting.get(node_index, []))):
                        socket = self.connect_to_node(zmq_ctx, node_index, recycled_connections)
                        assert socket
                        register_socket(socket)
                        nodes_contacted[socket] = node_index
                        nodes_requested[node_index] = nodes_requested.get(node_index, 0) + 1

                sockets = dict(poller.poll(1000))
                for socket, flags in sockets.items():
                    if flags != zmq.POLLIN:
                        continue

                    elif socket is client_socket:
                        with timer.timeit("poller.client"):
                            msg = client_socket.recv_multipart()
                            client_id = msg[0]
                            assert len(msg) == 2
                            assert msg[1][-2:] == b'\x00\x01'
                            parts = msg[1][:-2].split(b'\x00')
                            if client_id in session_from_client:
                                # Session already exists.
                                session = session_from_client[client_id]
                                server_socket = session.server_conn
                                assert server_socket in session_from_server
                                session.got_data_from_client(parts)
                            else:
                                # Create new session.
                                compiler = parts[0].decode()
                                executable = parts[1].decode()
                                sysincludes = parts[2].decode()
                                cwd = parts[3].decode()
                                command = [x.decode() for x in parts[4:]]
                                client_conn = self.SendProxy(client_socket, client_id)
                                client_conn.send([b"TASK_RECEIVED"])
                                node_index = self.best_node(node_info)
                                if nodes_waiting[node_index]:
                                    server_conn = nodes_waiting[node_index][0]
                                    del nodes_waiting[node_index][0]
                                    session = CompileSession(compiler, executable, cwd, sysincludes,
                                        command, timer, client_conn, server_conn,
                                        preprocess_socket, node_info[node_index], compiler_info)
                                    session_from_client[client_conn.id] = session
                                    session_from_server[server_conn] = session, node_index
                                else:
                                    clients_waiting.append((client_conn, compiler, executable, sysincludes, cwd, command))

                    elif socket in session_from_server:
                        with timer.timeit("poller.server_w_session"):
                            session, node_index = session_from_server[socket]
                            msg = socket.recv_multipart()
                            client_id = session.client_conn.id
                            assert client_id in session_from_client
                            session_done = session.got_data_from_server(msg)
                            if session_done:
                                del session_from_client[client_id]
                                del session_from_server[socket]
                                unregister_socket(socket)
                                recycled = recycled_connections.setdefault(
                                    node_index, [])
                                assert socket not in recycled
                                recycled.append(socket)
                    else: # Server
                        with timer.timeit("poller.server_wo_session"):
                            if socket in node_ids:
                                accept = socket.recv_pyobj()
                                node_index = node_ids[socket]
                                del node_ids[socket]
                                if accept == "ACCEPT":
                                    if clients_waiting:
                                        client_conn, compiler, executable, sysincludes, cwd, command = clients_waiting[0]
                                        del clients_waiting[0]
                                        session = CompileSession(compiler, executable, cwd, sysincludes,
                                            command, timer, client_conn, socket,
                                            preprocess_socket, node_info[node_index], compiler_info)
                                        session_from_client[client_conn.id] = session
                                        session_from_server[socket] = session, node_index
                                    else:
                                        nodes_waiting.setdefault(node_index, []).append(socket)
                                else:
                                    assert accept == "REJECT"
                                nodes_requested[node_index] -= 1
                            else:
                                assert socket in nodes_contacted
                                session_created = socket.recv()
                                assert session_created == b'SESSION_CREATED'
                                node_index = nodes_contacted[socket]
                                del nodes_contacted[socket]
                                node_ids[socket] = node_index
        finally:
            for scan_worker in scan_workers:
                scan_worker.terminate()

    def print_stats(self, node_info, timer, recycled_conections):
        current = time()
        if self.last_time and (current - self.last_time < 2):
            return False
        times = timer.as_dict()
        self.last_time = current
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:30} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Avg. Tasks {:<3.2f} '
                'Avg. Time {:<3.2f}\n'
            .format(
                node,
                node_info[index].tasks_sent       (),
                node_info[index].connections      (),
                node_info[index].tasks_completed  (),
                node_info[index].tasks_failed     (),
                node_info[index].tasks_processing (),
                node_info[index].average_tasks    (),
                node_info[index].average_task_time()))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
        sorted_times.sort(key=operator.itemgetter(1), reverse=True)
        for name, tm, count, average in sorted_times:
            print('{:-<30} Total {:->14.2f} Num {:->5} Average {:->14.2f}'.format(name, tm, count, average))
        return True

class NodeInfo:
    def __init__(self, index):
        self._index = index
        self._tasks_completed  = 0
        self._tasks_failed     = 0
        self._tasks_sent       = 0
        self._total_time       = 0
        self._open_connections = 0
        self._tasks_change     = None
        self._avg_tasks = {}

    def index(self):
        return self._index

    def average_task_time(self):
        tasks_completed = self.tasks_completed()
        return self.total_time() / tasks_completed if tasks_completed else 0

    def connection_open(self): self._open_connections += 1

    def connection_closed(self): self._open_connections -= 1

    def connections(self): return self._open_connections

    def tasks_sent(self): return self._tasks_sent

    def tasks_completed(self): return self._tasks_completed

    def tasks_failed(self): return self._tasks_failed

    def tasks_processing(self): return self.tasks_sent() - self.tasks_completed() - self.tasks_failed()

    def total_time(self): return self._total_time

    def average_tasks(self):
        avg_tasks = self._avg_tasks
        regular_duration = sum((duration for duration in avg_tasks.values()))
        weighted_duration = sum((duration * tasks for tasks, duration in avg_tasks.items()))
        return (weighted_duration / regular_duration) if regular_duration else 0

    def __tasks_processing_about_to_change(self):
        tasks_processing = self.tasks_processing()
        if tasks_processing > 0:
            current_time = time()
            duration = current_time - self._tasks_change
            self._tasks_change = current_time
            self._avg_tasks.setdefault(tasks_processing, 0)
            self._avg_tasks[tasks_processing] += duration
        else:
            self._tasks_change = time()

    def add_tasks_sent(self):
        self.__tasks_processing_about_to_change()
        self._tasks_sent += 1

    def add_tasks_completed(self):
        self.__tasks_processing_about_to_change()
        self._tasks_completed += 1

    def add_tasks_failed(self): self._add_tasks_failed += 1

    def add_total_time(self, value): self._total_time += value

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
            nodes.append('tcp://{}:{}'.format(value[:index], int(value[index+1:])))
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
