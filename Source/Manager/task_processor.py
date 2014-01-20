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

from Common import bind_to_random_port

import operator
import pickle
import sys
import zmq
import sched
import threading

from functools import cmp_to_key
from multiprocessing import cpu_count, Semaphore
from socket import getfqdn
from time import time

class TaskProcessor:
    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            try:
                self.socket.send_multipart([self.id, b'\x00'.join(data) + b'\x00\x01'], copy=False)
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

    class PreprocessorSockets:
        def __init__(self, zmq_ctx):
            self.pp_sockets = []
            self.zmq_ctx = zmq_ctx

        def get_socket(self):
            if self.pp_sockets:
                preprocess_socket = self.pp_sockets[0]
                del self.pp_sockets[0]
            else:
                preprocess_socket = self.zmq_ctx.socket(zmq.DEALER)
                preprocess_socket.connect('inproc://preprocessor')
            return preprocess_socket

        def return_socket(self, socket):
            assert socket not in self.pp_sockets
            self.pp_sockets.append(socket)

    class ClientServerRendezvous(Rendezvous):
        def __init__(self, timer, sessions, node_info, pp_sockets):
            Rendezvous.__init__(self, 'client_ready', 'server_ready')
            self.node_info = node_info
            self.sessions = sessions
            self.timer = timer
            self.pp_sockets = pp_sockets

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
            self.data[client_id] = self.data.get(client_id, b'') + data.tobytes()
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

        self.poller = zmq.Poller()

        self.zmq_ctx = zmq.Context()
        self.zmq_ctx2 = zmq.Context()
        self.source_scanner = SourceScanner()

        self.client_socket = create_socket(self.zmq_ctx, zmq.STREAM)
        self.client_socket.bind('tcp://*:{}'.format(self.__port))
        self.register_socket(self.client_socket)

        self.pp_sockets = self.PreprocessorSockets(self.zmq_ctx)
        self.csrv = self.ClientServerRendezvous(self.timer, self.sessions,
            self.node_info, self.pp_sockets)
        self.client_data = self.ClientData()

    def register_socket(self, socket):
        self.poller.register(socket, zmq.POLLIN)

    def unregister_socket(self, socket):
        self.poller.unregister(socket)

    def run_queue(self):
        notify_socket = create_socket(self.zmq_ctx2, zmq.PAIR)
        notify_socket.connect('inproc://preprocessing')
        fqdn = getfqdn()

        try:
            while True:
                client_id, header_info, async_wait_time, internal_time, (hits, misses) = \
                    self.source_scanner.completed_task()
                self.cache_info = hits, misses
                session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
                assert(session)
                self.timer.add_time('preprocessing.async_wait', async_wait_time)
                self.timer.add_time('preprocessing.internal', internal_time)
                # Add filelist to package which goes to the server.
                session.task.server_task_info['filelist'] = create_filelist(header_info)
                session.task.server_task_info['fqdn'] = fqdn
                session.task.header_info = header_info
                notify_socket.send_multipart([client_id, pickle.dumps(time())], copy=False)
        finally:
            notify_socket.disconnect('inproc://preprocessing')

    def run_poller(self):
        for connection in self.node_manager.spawn_connections(self.zmq_ctx):
            self.register_socket(connection)

        for socket, flags in dict(self.poller.poll(1000)).items():
            assert flags == zmq.POLLIN
            self.handle_socket(socket)

    def run(self):
        queue_thread = threading.Thread(target=self.run_queue)
        queue_thread.start()

        self.preprocessing_done = create_socket(self.zmq_ctx2, zmq.PAIR)
        self.preprocessing_done.bind('inproc://preprocessing')
        self.register_socket(self.preprocessing_done)

        try:
            while True:
                self.print_stats()
                self.run_poller()
        finally:
            self.source_scanner.terminate()
            queue_thread.join()
            self.poller.unregister(self.preprocessing_done)
            self.preprocessing_done.unbind('inproc://preprocessing')

    def handle_socket(self, socket):
        if socket is self.preprocessing_done:
            (client_id, start_time) = recv_multipart(socket)
            self.timer.add_time('preprocessing.notify_done', time() - pickle.loads(start_time))
            session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
            self.timer.add_time('preprocessing.external', session.pp_timer.get())
            self.csrv.client_ready((session, SimpleTimer()))
            server_result = self.node_manager.get_server_conn()
            if server_result:
                self.csrv.server_ready(server_result)

        elif socket is self.client_socket:
            with self.timer.timeit('poller.client'):
                client_id, data = recv_multipart(self.client_socket)
                messages = self.client_data.process_new_data(client_id, data)
                for msg in messages:
                    session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
                    if session:
                        session.got_data_from_client(msg)
                    else:
                        with self.timer.timeit('poller.client.no_sess'):
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

        else:
            with self.timer.timeit('poller.server'):
                # Connection to server node.
                result = self.sessions.get(self.Sessions.FROM_SERVER, socket)
                if result is not None:
                    # Part of a session.
                    session, node_index = result
                    msg = recv_multipart(socket)
                    client_id = session.client_conn.id
                    session_done = session.got_data_from_server(msg)
                    if session_done:
                        self.sessions.unregister(self.Sessions.FROM_SERVER, socket)
                        self.sessions.unregister(self.Sessions.FROM_CLIENT, client_id)
                        self.unregister_socket(socket)
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
                                server_result = self.node_manager.get_server_conn()
                                if server_result:
                                    self.csrv.server_ready(server_result)
                            else:
                                session.task.completed(session.client_conn,
                                    session.retcode, session.stdout, session.stderr)
                else:
                    # Not part of a session, handled by node_manager.
                    node_index = self.node_manager.handle_socket(socket)
                    if node_index is not None and self.csrv.first():
                        server_conn, node_index = self.node_manager.get_server_conn(node_index)
                        assert server_conn
                        self.csrv.server_ready((server_conn, node_index))

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
