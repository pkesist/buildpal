from Compilers import MSVCWrapper
from Common import SimpleTimer, Rendezvous, recv_multipart, create_socket

from .compile_session import CompileSession
from .source_scanner import SourceScanner
from .command_processor import CommandProcessor
from .timer import Timer
from .node_manager import NodeManager
from .poller import ZMQSelectPoller
from .console import ConsolePrinter

from Common import bind_to_random_port

import operator
import pickle
import sys
import zmq
import sched
import select
import socket
import threading

from multiprocessing import cpu_count
from socket import getfqdn
from time import time
from subprocess import list2cmdline

Poller = ZMQSelectPoller

class TaskProcessor:
    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            try:
                self.socket.send_multipart(
                    [self.id, b'\x00'.join(data) + b'\x00\x01'], copy=False)
            except zmq.error.ZMQError:
                # In case connection gets broken ZMQ raises an error.
                pass

        def recv(self):
            try:
                return recv_multipart(self.socket)
            except zmq.error.ZMQError:
                # In case connection gets broken ZMQ raises an error.
                pass

        def send_pyobj(self, obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    class Sessions:
        FROM_SERVER = 1

        def __init__(self):
            self.session = {self.FROM_SERVER : {}}

        def register(self, type, key, *val):
            self.session[type][key] = val

        def get(self, type, key):
            result = self.session[type].get(key)
            if result is None:
                return None
            assert isinstance(result, tuple)
            if len(result) == 1:
                return result[0]
            return result

        def unregister(self, type, key):
            try:
                del self.session[type][key]
            except Exception:
                import traceback
                traceback.print_exc()

        def close(self):
            for server_conn in self.session[self.FROM_SERVER]:
                server_conn.close()

    class ClientServerRendezvous(Rendezvous):
        def __init__(self, timer, sessions, node_info):
            Rendezvous.__init__(self, 'client_ready', 'server_ready')
            self.node_info = node_info
            self.sessions = sessions

        def match(self, task, server_tuple):
            server_conn, node = server_tuple
            session = CompileSession(task, server_conn, node)
            self.sessions.register(TaskProcessor.Sessions.FROM_SERVER, server_conn, session)
            session.start()

    class ClientData:
        def __init__(self):
            self.data = {}

        def __get_message(self, client_id):
            data = self.data.get(client_id, b'')
            try:
                end_index = data.index(b'\x00\x01')
            except ValueError:
                return None
            result = data[:end_index].split(b'\x00')
            data = data[end_index + 2:]
            if data:
                self.data[client_id] = data
            else:
                del self.data[client_id]
            return result

        def process_new_data(self, client_id, data):
            byte_data = data if type(data) == bytes else data.tobytes()
            self.data[client_id] = self.data.get(client_id, b'') + byte_data
            messages = []
            while True:
                x = self.__get_message(client_id)
                if x is not None:
                    messages.append(x)
                else:
                    break
            return messages

    def __init__(self, node_info, port, n_pp_threads, ui_data):
        class CacheStats:
            def __init__(self):
                self.hits = 0
                self.misses = 0
                self.ratio = 0.0

            def update(self, data):
                self.hits, self.misses = data
                total = self.hits + self.misses
                if total == 0:
                    total = 1
                self.ratio = self.hits / total

        self.port = port
        self.cache_stats = CacheStats()
        self.compiler_info = {}
        self.timer = Timer()
        self.node_info = node_info
        self.n_pp_threads = n_pp_threads
        if not self.n_pp_threads:
            self.n_pp_threads = cpu_count()

        self.ui_data = ui_data
        self.ui_data.timer = self.timer
        self.ui_data.node_info = self.node_info
        self.ui_data.cache_stats = self.cache_stats

    def register_socket(self, socket, handler):
        self.poller.register(socket, handler)

    def unregister_socket(self, socket):
        self.poller.unregister(socket)

    def notify_preprocessing_done(self):
        self.pp_ready()

    def __handle_preprocessing_done(self):
        fqdn = getfqdn()
        while True:
            pp_result_dict = self.source_scanner.completed_task()
            if not pp_result_dict:
                return
            # Update task
            task = pp_result_dict['task']
            assert hasattr(task, 'header_info')
            task.server_task_info['fqdn'] = fqdn
            task.server_task_info['filelist'] = create_filelist(task.header_info)

            # Update UI stuff
            self.timer.add_time('preprocessing.in_queue',
                pp_result_dict['time_in_in_queue'])
            self.timer.add_time('preprocessing.out_queue',
                time() - pp_result_dict['time_queued'])
            self.timer.add_time('preprocessing.internal',
                pp_result_dict['preprocessing_time'])
            self.timer.add_time('preprocessing.external',
                task.pp_timer.get())
            self.cache_stats.update(pp_result_dict['cache_stats'])

            DEBUG_just_preprocess = False
            if DEBUG_just_preprocess:
                session.client_conn.send([b'EXIT', b'0', b'', b''])
                return

            self.csrv.client_ready(task)
            server_result = self.node_manager.get_server_conn()
            if server_result:
                self.csrv.server_ready(server_result)

    def __handle_new_client(self, client_id, msg):
        compiler_name = msg[0].decode()
        executable = msg[1].decode()
        sysincludes = msg[2].decode()
        cwd = msg[3].decode()
        command = [x.decode() for x in msg[4:]]
        client_conn = self.SendProxy(self.client_socket,
            client_id.tobytes())
        client_conn.send([b'TASK_RECEIVED'])
        assert compiler_name == 'msvc'
        compiler = MSVCWrapper()
        cmd_processor = CommandProcessor(client_conn, executable,
            cwd, sysincludes, compiler, command)

        if cmd_processor.build_local():
            client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(command).encode()])
            return

        if executable in self.compiler_info:
            cmd_processor.set_compiler_info(self.compiler_info[executable])
            self.__create_tasks(cmd_processor)
        else:
            self.command_processor[client_id.tobytes()] = cmd_processor
            cmd_processor.request_compiler_info(on_completion=self.__create_tasks)

    def __create_tasks(self, cmd_processor):
        assert cmd_processor.state == cmd_processor.STATE_HAS_COMPILER_INFO
        if not cmd_processor.executable() in self.compiler_info:
            self.compiler_info[cmd_processor.executable()] = \
                cmd_processor.compiler_info
        for task in cmd_processor.create_tasks():
            task.server_task_info['compiler_info'] = task.compiler_info()
            task.preprocess_task_info['macros'].extend(
                task.compiler_info()['macros'])
            task.pp_timer = SimpleTimer()
            self.source_scanner.add_task(task)

    def __handle_client_socket(self, socket, msg):
        client_id, data = msg
        messages = self.client_data.process_new_data(client_id, data)
        for msg in messages:
            cmd_processor = self.command_processor.get(client_id)
            if cmd_processor:
                cmd_processor.got_data_from_client(msg)
            else:
                self.__handle_new_client(client_id, msg)

    def __handle_server_socket(self, socket, msg):
        # Connection to server node.
        session = self.sessions.get(self.Sessions.FROM_SERVER, socket)
        session_done = session.got_data_from_server(msg)
        if session_done:
            self.sessions.unregister(self.Sessions.FROM_SERVER, socket)
            self.node_manager.recycle(session.node, socket)
            task = session.task
            if session.state == session.STATE_DONE:
                assert task.is_completed()
                assert task.session_completed == session
                task.completed(session, session.retcode,
                    session.stdout, session.stderr)
            elif session.state == session.STATE_SERVER_FAILURE:
                if task.is_completed():
                    assert task.completed
                    assert task.session_completed != session
                    self.sessions.unregister(self.Sessions.FROM_SERVER, socket)
                    return
                if hasattr(task, 'retries'):
                    task.retries += 1
                else:
                    task.retries = 1
                if task.retries <= 3:
                    self.csrv.client_ready(task)
                    server_result = self.node_manager.get_server_conn()
                    if server_result:
                        self.csrv.server_ready(server_result)
                else:
                    # BUGGY
                    session.task.completed(session, session.retcode,
                        session.stdout, session.stderr)
            else:
                assert session.state == session.STATE_CANCELLED

    def run(self, observer=None):
        self.command_processor = {}
        self.sessions = self.Sessions()
        self.zmq_ctx = zmq.Context()
        register_server_socket = lambda socket : self.register_socket(socket,
            self.__handle_server_socket)
        self.poller = Poller(self.zmq_ctx)
        self.node_manager = NodeManager(self.zmq_ctx, self.node_info,
            register_server_socket, self.unregister_socket)
        self.source_scanner = SourceScanner(self.notify_preprocessing_done, self.n_pp_threads)

        # Setup socket for receiving clients.
        self.client_socket = create_socket(self.zmq_ctx, zmq.STREAM)
        self.client_socket.bind('tcp://*:{}'.format(self.port))
        self.register_socket(self.client_socket, self.__handle_client_socket)

        self.csrv = self.ClientServerRendezvous(self.timer, self.sessions,
            self.node_info)
        self.client_data = self.ClientData()
        self.pp_ready = self.poller.create_event(
            self.__handle_preprocessing_done)

        try:
            if observer is None:
                observer = ConsolePrinter(self.node_info, self.ui_data)
            self.poller.run(observer)
        finally:
            self.client_socket.close()
            self.source_scanner.close()
            self.pp_ready.close()
            self.node_manager.close()
            self.sessions.close()
            self.poller.close()
            self.zmq_ctx.term()

    def stop(self):
        self.poller.stop()

def create_filelist(header_info):
    result = []
    for dir, content in header_info:
        dir_data = []
        for file, relative, content, checksum, header in content:
            # Headers which are relative to source file are not
            # considered as candidates for server cache, and are
            # always sent together with the source file.
            if not relative:
                dir_data.append((file, checksum))
        result.append((dir, dir_data))
    return tuple(result)
