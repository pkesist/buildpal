#! python3.3
from cmdline_processing import *
from functools import cmp_to_key
from multiprocessing import Process, cpu_count
from time import sleep, time
from msvc import MSVCWrapper
from subprocess import list2cmdline

from scan_headers import collect_headers
from utils import send_file, send_compressed_file

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

class SimpleTimer:
    def __init__(self):
        self.__start = time()

    def get(self):
        return time() - self.__start


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
            timer = SimpleTimer()
            buffer = self.prepare_task(pickle.loads(task))
            socket.send_multipart([client_id, pickle.dumps(timer.get()), buffer.read()], copy=False)

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
            self.client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(call).encode()])
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
            self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
            self.preprocess_socket.send_multipart([self.client_conn.id, pickle.dumps(self.task.preprocess_task_info)], copy=False)
            self.preprocess_timer = self.timer.scoped_timer('preprocess.external')
            self.task.server_task_info['compiler_info'] = self.task.compiler_info
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
        retcode = int(msg[1])
        stdout = msg[2]
        stderr = msg[3]
        info = self.compiler.compiler_info(self.executable, stdout, stderr)
        self.compiler_info[self.executable] = info
        self.task.compiler_info = self.compiler_info[self.executable]
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
        self.preprocess_socket.send_multipart([self.client_conn.id, pickle.dumps(self.task.preprocess_task_info)], copy=False)
        self.preprocess_timer = self.timer.scoped_timer('preprocess.external')
        self.task.server_task_info['compiler_info'] = self.task.compiler_info
        with self.timer.timeit('send'):
            self.server_conn.send_pyobj(self.task.server_task_info)
        self.node_info.add_tasks_sent()
        self.state = self.STATE_WAIT_FOR_OK

    def send_task_files(self):
        self.server_conn.send_pyobj('TASK_FILES')
        # Source file is already inside the tar archive.
        tar_obj = io.BytesIO(self.tempfile)
        tar_obj.seek(0)
        self.server_timer = self.timer.scoped_timer('server_time.external')
        self.average_timer = ScopedTimer(lambda value : self.node_info.add_total_time(value))
        with self.timer.timeit('send.tar'):
            send_file(self.server_conn.send_multipart, tar_obj, copy=False)
        del tar_obj
        del self.tempfile
        source_file = self.task.source
        self.server_conn.send_pyobj(('SOURCE_FILE', source_file))
        self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_OK:
            task_ok = msg[0]
            assert msg[0] == b'OK'
            if self.task.pch_file:
                self.server_conn.send_pyobj('NEED_PCH_FILE')
                self.state = self.STATE_WAIT_FOR_PCH_RESPONSE
            else:
                self.send_task_files()

        elif self.state == self.STATE_WAIT_FOR_PCH_RESPONSE:
            response = msg[0]
            if response == b'YES':
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_multipart, pch_file, copy=False)
            else:
                assert response == b'NO'
            self.send_task_files()

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            self.server_timer.stop()
            del self.server_timer
            self.average_timer.stop()
            del self.average_timer
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.client_conn.send([b'EXIT', b'-1'])
                self.state = self.STATE_WAIT_FOR_SESSION_DONE
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, compile_time = pickle.loads(msg[1])
                self.timer.add_time('server_time.compiler', compile_time)
                if self.retcode == 0:
                    self.output = open(self.task.output, "wb")
                    self.output_decompressor = zlib.decompressobj()
                    self.state = self.STATE_RECEIVE_RESULT_FILE
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

        super(TaskProcessor, self).__init__()

    def find_available_node(self, node_info, zmq_ctx, recycled_connections):
        def cmp(lhs, rhs):
            lhs_tasks_processing = node_info[lhs].tasks_processing() + node_info[lhs].reserved_connections()
            rhs_tasks_processing = node_info[rhs].tasks_processing() + node_info[rhs].reserved_connections()
            lhs_time_per_task = node_info[lhs].average_task_time()
            rhs_time_per_task = node_info[rhs].average_task_time()
            if lhs_time_per_task == 0 and rhs_time_per_task == 0:
                return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
            if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
                return -1 if lhs_time_per_task < rhs_time_per_task else 1
            return -1 if lhs_tasks_processing * lhs_time_per_task <= rhs_tasks_processing * rhs_time_per_task else 1
        compare_key = cmp_to_key(cmp)

        order = list(range(len(self.__nodes)))
        order.sort(key=compare_key)
        for node_index in order:
            recycled = recycled_connections.get(node_index)
            if recycled:
                socket = recycled[0]
                del recycled[0]
            else:
                node = self.__nodes[node_index]
                try:
                    socket = zmq_ctx.socket(zmq.DEALER)
                    socket.connect('tcp://{}:{}'.format(node[0], node[1]))
                except Exception:
                    print("Failed to connect to '{}'".format(node))
                    import traceback
                    traceback.print_exc()
                    continue
            socket.send(b'CREATE_SESSION')
            node_info[node_index].inc_reserved_connections()
            return socket, node_index
        return None

    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            self.socket.send_multipart([self.id] + data, copy=False)

        def recv(self):
            return self.socket.recv_multipart()

        def send_pyobj(self, obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    def run(self):
        zmq_ctx = zmq.Context()
        client_socket = zmq_ctx.socket(zmq.ROUTER)
        client_socket.bind('tcp://*:{}'.format(self.__port))

        preprocess_socket = zmq_ctx.socket(zmq.DEALER)
        preprocess_socket_port = preprocess_socket.bind_to_random_port('tcp://*')

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
        register_socket(preprocess_socket)

        compiler_info = {}

        self.last_time = None

        timer = Timer()

        node_info = [NodeInfo() for x in range(len(self.__nodes))]

        scan_workers = [ScanHeaders(preprocess_socket_port, timer) for i in range(cpu_count() + 2)]
        for scan_worker in scan_workers:
            scan_worker.start()

        max_nodes_waiting = 8
        nodes_requested = 0

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
        nodes_waiting = []

        # Clients waiting for a node.
        clients_waiting = []

        try:
            while True:
                self.print_stats(node_info, timer, recycled_connections)
                for x in range(max_nodes_waiting - len(nodes_waiting) - nodes_requested):
                    result = self.find_available_node(node_info, zmq_ctx, recycled_connections)
                    if result is not None:
                        socket, node_index = result
                        register_socket(socket)
                        nodes_contacted[socket] = node_index
                        nodes_requested += 1

                sockets = dict(poller.poll(1000))
                for socket, flags in sockets.items():
                    if flags != zmq.POLLIN:
                        continue

                    if socket is preprocess_socket:
                        with timer.timeit("poller.preprocess"):
                            try:
                                while True:
                                    client_id, duration, buffer = preprocess_socket.recv_multipart(flags=zmq.NOBLOCK)
                                    timer.add_time('preprocess.internal', pickle.loads(duration))
                                    assert client_id in session_from_client
                                    session = session_from_client[client_id]
                                    session.preprocess_timer.stop()
                                    del session.preprocess_timer
                                    session.tempfile = buffer
                                    register_socket(session.server_conn)
                            except zmq.ZMQError:
                                pass

                    elif socket is client_socket:
                        with timer.timeit("poller.client"):
                            msg = client_socket.recv_multipart()
                            client_id = msg[0]
                            if client_id in session_from_client:
                                # Session already exists.
                                session = session_from_client[client_id]
                                server_socket = session.server_conn
                                assert server_socket in session_from_server
                                session.got_data_from_client(msg)
                            else:
                                # Create new session.
                                compiler = msg[1].decode()
                                executable = msg[2].decode()
                                sysincludes = msg[3].decode()
                                cwd = msg[4].decode()
                                command = [x.decode() for x in msg[4:]]
                                client_conn = self.SendProxy(client_socket, client_id)
                                client_conn.send([b"TASK_RECEIVED"])
                                if nodes_waiting:
                                    server_conn, node_index = nodes_waiting[0]
                                    del nodes_waiting[0]
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
                                # Temporarily unregister this socket. It will be
                                # registered again when its preprocessing is
                                # done.
                                unregister_socket(socket)
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
                                        nodes_waiting.append((socket, node_index))
                                else:
                                    assert accept == "REJECT"
                                    node_info[node_index].dec_reserved_connections()
                                nodes_requested -= 1
                            else:
                                assert socket in nodes_contacted
                                session_created = socket.recv()
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
            sys.stdout.write('{:15}:{:5} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Reserved {:<3} '
                'Avg. Tasks {:<3.2f} Avg. Time {:<3.2f}\n'
            .format(
                node[0], node[1],
                node_info[index].tasks_sent          (),
                node_info[index].connections         (),
                node_info[index].tasks_completed     (),
                node_info[index].tasks_failed        (),
                node_info[index].tasks_processing    (),
                node_info[index].reserved_connections(),
                node_info[index].average_tasks       (),
                node_info[index].average_task_time   ()))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
        sorted_times.sort(key=operator.itemgetter(1), reverse=True)
        for name, tm, count, average in sorted_times:
            print('{:-<30} Total {:->10.2f} Num {:->5} Average {:->10.2f}'.format(name, tm, count, average))
        return True

class NodeInfo:
    def __init__(self):
        self._tasks_completed      = 0
        self._tasks_failed         = 0
        self._tasks_sent           = 0
        self._total_time           = 0
        self._open_connections     = 0
        self._reserved_connections = 0
        self._tasks_change         = None
        self._avg_tasks = {}

    def average_task_time(self):
        tasks_completed = self.tasks_completed()
        return self.total_time() / tasks_completed if tasks_completed else 0

    def connection_open(self): self._open_connections += 1

    def connection_closed(self): self._open_connections -= 1

    def connections(self): return self._open_connections

    def reserved_connections(self): return self._reserved_connections

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

    def inc_reserved_connections(self):
        self._reserved_connections += 1

    def dec_reserved_connections(self):
        self._reserved_connections -= 1

    def add_tasks_sent(self):
        self.__tasks_processing_about_to_change()
        assert self.reserved_connections() > 0
        self._reserved_connections -= 1
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
