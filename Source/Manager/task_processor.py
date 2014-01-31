from Compilers import MSVCWrapper
from Common import SimpleTimer, Rendezvous
from Common import create_socket, recv_multipart

from .compile_session import CompileSession
from .node_info import NodeInfo
from .source_scanner import SourceScanner
from .timer import Timer
from .task_creator import create_tasks
from .node_manager import NodeManager
from .scan_headers import dump_cache
from .poller import OSSelectPoller

from Common import bind_to_random_port

import operator
import pickle
import sys
import zmq
import sched
import select
import socket
import threading

from functools import cmp_to_key
from multiprocessing import cpu_count, Semaphore
from socket import getfqdn
from time import time

Poller = OSSelectPoller

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
        FROM_CLIENT = 0
        FROM_SERVER = 1

        def __init__(self):
            self.session = {self.FROM_CLIENT : {}, self.FROM_SERVER : {}}

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

    class ClientServerRendezvous(Rendezvous):
        def __init__(self, timer, sessions, node_info):
            Rendezvous.__init__(self, 'client_ready', 'server_ready')
            self.node_info = node_info
            self.sessions = sessions
            self.timer = timer

        def match(self, client_tuple, server_tuple):
            session, timer = client_tuple
            server_conn, node_index = server_tuple
            self.timer.add_time('waiting.server', timer.get())
            self.sessions.register(TaskProcessor.Sessions.FROM_SERVER, server_conn, session, node_index)
            session.preprocessing_done(server_conn, self.node_info[node_index])

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

    def __init__(self, nodes, port):
        self.__port = port
        self.__nodes = nodes
        self.cache_info = (0, 0)
        self.compiler_info = {}
        self.timer = Timer()
        self.node_info = [NodeInfo(self.__nodes[x], x) for x in range(len(self.__nodes))]
        self.sessions = self.Sessions()
        self.node_manager = NodeManager(self.node_info)

        self.zmq_ctx = zmq.Context()

        self.poller = Poller(self.zmq_ctx)

        self.source_scanner = SourceScanner(self.notify_preprocessing_done)

        self.client_socket = create_socket(self.zmq_ctx, zmq.STREAM)
        self.client_socket.bind('tcp://*:{}'.format(self.__port))
        self.register_socket(self.client_socket, self.__handle_client_socket)

        self.csrv = self.ClientServerRendezvous(self.timer, self.sessions,
            self.node_info)
        self.client_data = self.ClientData()

    def register_socket(self, socket, handler):
        self.poller.register(socket, handler)

    def unregister_socket(self, socket):
        self.poller.unregister(socket)

    def notify_preprocessing_done(self):
        self.pp_ready()

    def __handle_preprocessing_done(self):
        fqdn = getfqdn()
        while True:
            result = self.source_scanner.completed_task()
            if not result:
                break
            client_id, header_info, time_in_in_queue, preprocessing_time, \
                time_queued, (hits, misses) = result
            time_in_out_queue = time() - time_queued
            self.cache_info = hits, misses
            session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
            assert(session)
            self.timer.add_time('preprocessing.in_queue', time_in_in_queue)
            self.timer.add_time('preprocessing.out_queue', time_in_out_queue)
            self.timer.add_time('preprocessing.internal', preprocessing_time)
            # Add filelist to package which goes to the server.
            session.task.server_task_info['filelist'] = create_filelist(header_info)
            session.task.server_task_info['fqdn'] = fqdn
            session.task.header_info = header_info
            session = self.sessions.get(self.Sessions.FROM_CLIENT,
                client_id)
            self.timer.add_time('preprocessing.external', session.pp_timer.get())
            DEBUG_just_preprocess = False
            if DEBUG_just_preprocess:
                session.client_conn.send([b'EXIT', b'0', b'', b''])
                self.sessions.unregister(self.Sessions.FROM_CLIENT, session.client_conn.id)
            else:
                self.csrv.client_ready((session, SimpleTimer()))
                server_result = self.node_manager.get_server_conn(self.zmq_ctx,
                    lambda socket : self.register_socket(socket,
                    self.__handle_server_socket))
                if server_result:
                    self.csrv.server_ready(server_result)

    def __handle_client_socket(self, socket, msg):
        client_id, data = msg
        messages = self.client_data.process_new_data(client_id, data)
        for msg in messages:
            session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
            if session:
                session.got_data_from_client(msg)
            else:
                # Create new session.
                compiler_name = msg[0].decode()
                executable = msg[1].decode()
                sysincludes = msg[2].decode()
                cwd = msg[3].decode()
                command = [x.decode() for x in msg[4:]]
                client_conn = self.SendProxy(self.client_socket, client_id.tobytes())
                client_conn.send([b'TASK_RECEIVED'])
                assert compiler_name == 'msvc'
                compiler = MSVCWrapper()
                def preprocess_task(session):
                    session.pp_timer = SimpleTimer()
                    self.source_scanner.add_task(session.task)
                for task in create_tasks(client_conn, compiler,
                    executable, cwd, sysincludes, command):
                    session = CompileSession(task, preprocess_task,
                        self.compiler_info)
                    self.sessions.register(self.Sessions.FROM_CLIENT,
                        client_id, session)
                    session.begin()

    def __handle_server_socket(self, socket, msg):
        # Connection to server node.
        result = self.sessions.get(self.Sessions.FROM_SERVER, socket)
        if result is not None:
            # Part of a session.
            session, node_index = result
            client_id = session.client_conn.id
            session_done = session.got_data_from_server(msg)
            if session_done:
                self.sessions.unregister(self.Sessions.FROM_SERVER, socket)
                self.sessions.unregister(self.Sessions.FROM_CLIENT, client_id)
                self.node_manager.recycle(node_index, socket)
                if session.state == session.STATE_DONE:
                    session.task.completed(session.retcode,
                        session.stdout, session.stderr)
                else:
                    assert session.state == session.STATE_SERVER_FAILURE
                    if hasattr(task, 'retries'):
                        task.retries += 1
                    else:
                        task.retries = 1
                    if task.retries <= 3:
                        session.rewind()
                        self.csrv.client_ready((session, SimpleTimer()))
                        server_result = self.node_manager.get_server_conn(
                            self.zmq_ctx, lambda socket : self.register_socket(
                            socket, self.__handle_server_socket))
                        if server_result:
                            self.csrv.server_ready(server_result)
                    else:
                        session.task.completed(session.client_conn,
                            session.retcode, session.stdout, session.stderr)
        else:
            # Not part of a session, handled by node_manager.
            node_index = self.node_manager.handle_socket(socket, msg)
            if node_index is not None and self.csrv.first():
                register_func = lambda socket : self.register_socket(socket,
                    self.__handle_server_socket)
                server_conn, node_index = self.node_manager.get_server_conn(
                    self.zmq_ctx, register_func, node_index)
                assert server_conn
                self.csrv.server_ready((server_conn, node_index))

    def run(self):
        self.pp_ready = self.poller.create_event(self.__handle_preprocessing_done)

        try:
            self.poller.run(self.print_stats)
        finally:
            self.source_scanner.terminate()
            self.pp_ready.close()

    def print_stats(self):
        current_time = time()
        if hasattr(self, 'last_print') and (current_time - self.last_print) < 2:
            return
        self.last_print = current_time
        print("================")
        print("Build nodes:")
        print("================")
        for index in range(len(self.node_info)):
            node = self.node_info[index]
            print('{:30} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Avg. Tasks {:<3.2f} '
                'Avg. Time {:<3.2f}'
            .format(
                node.node_dict()['address'],
                node.tasks_sent       (),
                node.connections      (),
                node.tasks_completed  (),
                node.tasks_failed     (),
                node.tasks_processing (),
                node.average_tasks    (),
                node.average_task_time()))
        print("================")
        print("in_queue_size {}".format(self.source_scanner.in_queue.qsize()))
        print("out_queue_size {}".format(self.source_scanner.out_queue.qsize()))
        print("================")
        def print_times(times):
            sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
            sorted_times.sort(key=operator.itemgetter(1), reverse=True)
            for name, tm, count, average in sorted_times:
                print('{:-<30} Total {:->14.2f} Num {:->5} Average {:->14.2f}'.format(name, tm, count, average))
        print_times(self.timer.as_dict())
        print("================")
        total_hits = self.cache_info[0]
        total_misses = self.cache_info[1]
        total = total_hits + total_misses
        if not total: total = 1
        print("Hits: {:8} Misses: {:8} Ratio: {:>.2f}".format(total_hits,
            total_misses, total_hits / total))
        print("================")
        for index in range(len(self.node_info)):
            node = self.node_info[index]
            times = node.timer().as_dict()
            if not times:
                continue
            print("================")
            print("Statistics for '{}'".format(node.node_dict()['address']))
            print("================")
            print_times(times)
            print("================")
            print("Server time difference - {}".format(times.get('server_time', (0, 0))[0] - times.get('server.server_time', (0, 0))[0]))
            total = 0
            for x in (
                'wait_for_header_list',
                'process_hdr_list',
                'wait_for_headers',
                'shared_prepare_dir',
                'async_compiler_delay',
                'compiler_prep',
                'compiler',):
                total += times.get('server.' + x, (0,0))[0]
            print("Discrepancy - {}".format(times.get('server_time', (0, 0))[0] - total))


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
