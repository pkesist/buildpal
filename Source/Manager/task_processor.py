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

from functools import cmp_to_key
from multiprocessing import cpu_count, Semaphore
from time import time

class TaskProcessor:
    def __init__(self, nodes, port):
        self.__port = port
        self.__nodes = nodes

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

    def run(self):
        zmq_ctx = zmq.Context()
        client_socket = create_socket(zmq_ctx, zmq.STREAM)
        client_socket.bind('tcp://*:{}'.format(self.__port))

        poller = zmq.Poller()

        register_socket = lambda socket : poller.register(socket, zmq.POLLIN)
        unregister_socket = lambda socket : poller.unregister(socket)

        register_socket(client_socket)

        self.cache_info = (0, 0)

        compiler_info = {}

        node_info = [NodeInfo(self.__nodes[x], x) for x in range(len(self.__nodes))]

        source_scanner = SourceScanner(zmq_ctx, 'inproc://preprocessor', self.__nodes, poller)
        class Sessions:
            FROM_CLIENT = 0
            FROM_PREPR  = 1
            FROM_SERVER = 2

            def __init__(self):
                self.session = {self.FROM_CLIENT : {}, self.FROM_PREPR : {},
                                self.FROM_SERVER : {}}

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
                del self.session[type][key]

        sessions = Sessions()

        node_manager = NodeManager(node_info)

        self.timer = Timer()

        class PreprocessorSockets:
            def __init__(self):
                self.pp_sockets = []

            def get_socket(self):
                if self.pp_sockets:
                    preprocess_socket = self.pp_sockets[0]
                    del self.pp_sockets[0]
                else:
                    preprocess_socket = zmq_ctx.socket(zmq.DEALER)
                    preprocess_socket.connect('inproc://preprocessor')
                return preprocess_socket

            def return_socket(self, socket):
                assert socket not in self.pp_sockets
                self.pp_sockets.append(socket)

        pp_sockets = PreprocessorSockets()

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
                sessions.register(Sessions.FROM_SERVER, server_conn, session, node_index)
                session.preprocessing_done(server_conn, self.node_info[node_index])
                pp_sockets.return_socket(session.preprocess_socket)
                del session.preprocess_socket

        csrv = ClientServerRendezvous(self.timer, sessions, node_info)

        def start_task(task):
            pp_socket = pp_sockets.get_socket()
            session = CompileSession(compiler, executable, task, client_conn,
                pp_socket, compiler_info)
            sessions.register(Sessions.FROM_CLIENT, client_conn.id, session)
            sessions.register(Sessions.FROM_PREPR, pp_socket, session)
            register_socket(pp_socket)

        scheduler = sched.scheduler()

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
        client_data = ClientData()

        try:
            while True:
                self.print_stats(node_info)
                node_connections = node_manager.spawn_connections(zmq_ctx)
                for connection in node_connections:
                    register_socket(connection)

                for socket, flags in dict(poller.poll(1000)).items():
                    if flags != zmq.POLLIN:
                        continue

                    with self.timer.timeit("poller.preprocessor_out"):
                        if source_scanner.handle(socket):
                            continue

                    session = sessions.get(Sessions.FROM_PREPR, socket)
                    if session:
                        with self.timer.timeit("poller.preprocessor_in"):
                            assert socket is session.preprocess_socket
                            msg = recv_multipart(socket)
                            assert msg[0] == b'PREPROCESSING_DONE'
                            self.timer.add_time('preprocessing.internal', pickle.loads(msg[1]))
                            self.timer.add_time('preprocessing.external', session.preprocessing_time.get())
                            hits, misses = pickle.loads(msg[2])
                            self.cache_info = hits, misses
                            # We will not be receiving throught this socket
                            # anymore, but we still need it to send data to
                            # server. It will be marked for reuse in
                            # client-server randezvous.
                            sessions.unregister(Sessions.FROM_PREPR, socket)
                            unregister_socket(socket)
                            # Useful toggle for profiling preprocessor.
                            DEBUG_JUST_PREPROCESS = False
                            if DEBUG_JUST_PREPROCESS:
                                # At this point preprocessing is done.
                                # Notify client to exit with success errorcode,
                                # so build can pump further tasks. The task will
                                # not be actually compiled.
                                session.client_conn.send([b'EXIT', b'0'])
                                socket.send_multipart([b'DROP'])
                                sessions.unregister(Sessions.FROM_CLIENT, session.client_conn.id)
                            else:
                                csrv.client_ready((session, SimpleTimer()))
                                server_result = node_manager.get_server_conn()
                                if server_result:
                                    csrv.server_ready(server_result)
                    elif socket is client_socket:
                        with self.timer.timeit('poller.client'):
                            client_id, data = recv_multipart(client_socket)
                            messages = client_data.process_new_data(client_id, data)
                            for msg in messages:
                                session = sessions.get(Sessions.FROM_CLIENT, client_id)
                                if session:
                                    session.got_data_from_client(msg)
                                else:
                                    # Create new session.
                                    compiler_name = msg[0].decode()
                                    executable = msg[1].decode()
                                    sysincludes = msg[2].decode()
                                    cwd = msg[3].decode()
                                    command = [x.decode() for x in msg[4:]]
                                    client_conn = self.SendProxy(client_socket, client_id.tobytes())
                                    client_conn.send([b'TASK_RECEIVED'])
                                    assert compiler_name == 'msvc'
                                    compiler = MSVCWrapper()
                                    for task in create_tasks(client_conn, compiler,
                                        executable, cwd, sysincludes, command):
                                        start_task(task)
                    else:
                        with self.timer.timeit('poller.server'):
                            # Connection to server node.
                            result = sessions.get(Sessions.FROM_SERVER, socket)
                            if result is not None:
                                # Part of a session.
                                session, node_index = result
                                msg = recv_multipart(socket)
                                client_id = session.client_conn.id
                                session_done = session.got_data_from_server(msg)
                                if session_done:
                                    sessions.unregister(Sessions.FROM_SERVER, socket)
                                    sessions.unregister(Sessions.FROM_CLIENT, client_id)
                                    unregister_socket(socket)
                                    node_manager.recycle(node_index, socket)
                                    if session.state == session.STATE_DONE:
                                        session.task.task_done(session.client_conn,
                                        session.retcode, session.stdout, session.stderr)
                                    elif session.state == session.STATE_SERVER_FAILURE:
                                        if hasattr(task, 'retries'):
                                            task.retries += 1
                                        else:
                                            task.retries = 1
                                        if task.retries <= 3:
                                            start_task(task)
                                        else:
                                            session.task.task_done(session.client_conn,
                                                session.retcode, session.stdout, session.stderr)
                            else:
                                # Not part of a session, handled by node_manager.
                                node_index = node_manager.handle_socket(socket)
                                if node_index is not None and csrv.first():
                                    server_conn, node_index = node_manager.get_server_conn(node_index)
                                    assert server_conn
                                    csrv.server_ready((server_conn, node_index))
                scheduler.run(False)
        finally:
            source_scanner.terminate()

    def print_stats(self, node_info):
        current = time()
        if hasattr(self, 'last_time') and (current - self.last_time < 2):
            return False
        self.last_time = current
        print("================")
        print("Build nodes:")
        print("================")
        for index in range(len(node_info)):
            node = node_info[index]
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
        for index in range(len(node_info)):
            node = node_info[index]
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
        return True
