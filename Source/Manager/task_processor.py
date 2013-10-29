from Compilers import MSVCWrapper
from Common import SimpleTimer, Rendezvous

from .compile_session import CompileSession
from .node_info import NodeInfo
from .source_scanner import SourceScanner
from .timer import Timer
from .task_creator import create_tasks

from Common import bind_to_random_port

import operator
import pickle
import sys
import zmq

from functools import cmp_to_key
from multiprocessing import cpu_count
from time import time
from struct import pack

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
                return self.socket.recv_multipart()
            except zmq.error.ZMQError:
                # In case connection gets broken ZMQ raises an error.
                pass

        def send_pyobj(self, obj):
            self.send([pickle.dumps(obj)])

        def recv_pyobj(self):
            return pickle.loads(self.recv()[0])

    def run(self):
        zmq_ctx = zmq.Context()
        client_socket = zmq_ctx.socket(zmq.STREAM)
        client_socket.bind('tcp://*:{}'.format(self.__port))

        preprocess_socket = zmq_ctx.socket(zmq.ROUTER)
        preprocess_socket_port = bind_to_random_port(preprocess_socket)

        poller = zmq.Poller()

        register_socket = lambda socket : poller.register(socket, zmq.POLLIN)
        unregister_socket = lambda socket : poller.unregister(socket)

        register_socket(client_socket)
        register_socket(preprocess_socket)

        compiler_info = {}

        node_info = [NodeInfo(self.__nodes[x], x) for x in range(len(self.__nodes))]

        scan_workers = [SourceScanner(preprocess_socket_port, self.__nodes) for i in range(cpu_count() * 2)]
        for scan_worker in scan_workers:
            scan_worker.start()

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

        class NodeManager:
            STATE_SOCKET_OPEN = 0
            STATE_SOCKET_RESPONDED = 1
            STATE_SOCKET_READY = 2

            CONNECTIONS_PER_NODE = 16

            def __init__(self, node_info):
                self.sockets_registered = {}
                self.sockets_ready = {}
                self.sockets_requested = {}
                self.recycled_connections = {}
                self.node_info = node_info
                self.__unique_id = 0

            def spawn_connections(self):
                result = []
                for node_index in range(len(self.node_info)):
                    for x in range(self.CONNECTIONS_PER_NODE - self.node_connections(node_index)):
                        socket = self.connect_to_node(zmq_ctx, node_index)
                        if not socket:
                            break
                        result.append(socket)
                return result

            def connect_to_node(self, zmq_ctx, node_index):
                recycled = self.recycled_connections.get(node_index)
                if recycled:
                    socket = recycled[0]
                    del recycled[0]
                else:
                    node_address = self.node_info[node_index].node_dict()['address']
                    try:
                        socket = zmq_ctx.socket(zmq.DEALER)
                        socket.setsockopt(zmq.IDENTITY, b'A' + pack('>I', self.__unique_id))
                        self.__unique_id += 1
                        socket.connect(node_address)
                    except zmq.ZMQError:
                        print("Failed to connect to '{}'".format(node_address))
                        return None
                socket.send(b'CREATE_SESSION')
                self.register(socket, node_index)
                return socket
            
            def best_node(self):
                def cmp(lhs, rhs):
                    lhs_node = self.node_info[lhs]
                    rhs_node = self.node_info[rhs]
                    lhs_tasks_processing = lhs_node.tasks_processing()
                    rhs_tasks_processing = rhs_node.tasks_processing()

                    def time_per_task(node):
                        timer = node.timer().as_dict()
                        hl_total, hl_count = timer.get('server.wait_for_header_list', (0, 1))
                        h_total, h_count = timer.get('server.wait_for_headers', (0, 1))
                        return node.average_task_time() - hl_total / hl_count + h_total / h_count

                    lhs_time_per_task = time_per_task(lhs_node)
                    rhs_time_per_task = time_per_task(rhs_node)

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
                return min(range(len(self.node_info)), key=compare_key)

            def recycle(self, node_index, socket):
                recycled = self.recycled_connections.setdefault(
                    node_index, [])
                assert socket not in recycled
                recycled.append(socket)

            def register(self, socket, node_index):
                self.sockets_registered[socket] = (node_index, self.STATE_SOCKET_OPEN)
                self.sockets_requested[node_index] = self.sockets_requested.get(node_index, 0) + 1

            def get_server_conn(self, node_index=None):
                if node_index is None:
                    node_index = self.best_node()
                if node_index is None:
                    return None
                node_sockets = self.sockets_ready.get(node_index)
                if not node_sockets:
                    return None
                socket = node_sockets[0]
                del node_sockets[0]
                del self.sockets_registered[socket]
                return socket, node_index

            def node_connections(self, node_index):
                return self.sockets_requested.get(node_index, 0) + \
                    len(self.sockets_ready.setdefault(node_index, []))

            def handle_socket(self, socket):
                node_index, state = self.sockets_registered[socket]
                if state == self.STATE_SOCKET_OPEN:
                    session_created = socket.recv()
                    assert session_created == b'SESSION_CREATED'
                    self.sockets_registered[socket] = node_index, self.STATE_SOCKET_RESPONDED
                    return None
                else:
                    assert state == self.STATE_SOCKET_RESPONDED
                    accept = socket.recv_pyobj()
                    self.sockets_requested[node_index] -= 1
                    if accept == "ACCEPT":
                        self.sockets_registered[socket] = node_index, self.STATE_SOCKET_READY
                        self.sockets_ready.setdefault(node_index, []).append(socket)
                        return node_index
                    else:
                        assert accept == "REJECT"
                        del self.sockets_registered[socket]
                        return None

        node_manager = NodeManager(node_info)

        self.timer = Timer()

        class ClientPreprocessorRendezvous(Rendezvous):
            def __init__(self, timer, sessions, compiler_info):
                Rendezvous.__init__(self, 'preprocessor_ready', 'client_ready')
                self.timer = timer
                self.sessions = sessions
                self.compiler_info = compiler_info

            def match(self, preprocessor_id, client_tuple):
                compiler, executable, task, client_conn, timer = client_tuple
                self.timer.add_time('waiting.preprocessor', timer.get())
                session = CompileSession(compiler, executable, task,
                    client_conn, preprocess_socket,
                    preprocessor_id, compiler_info)
                sessions.register(Sessions.FROM_CLIENT,
                    client_conn.id, session)
                sessions.register(Sessions.FROM_PREPR,
                    preprocessor_id, session)

        cprv = ClientPreprocessorRendezvous(self.timer, sessions, compiler_info)

        class ClientServerRendezvous(Rendezvous):
            def __init__(self, timer, sessions, node_info, cprv):
                Rendezvous.__init__(self, 'client_ready', 'server_ready')
                self.node_info = node_info
                self.sessions = sessions
                self.cprv = cprv
                self.timer = timer

            def match(self, client_tuple, server_tuple):
                session, preprocessor_id, timer = client_tuple
                server_conn, node_index = server_tuple
                self.timer.add_time('waiting.server', timer.get())
                session.preprocessing_done(server_conn, self.node_info[node_index])
                sessions.register(Sessions.FROM_SERVER, server_conn, session, node_index)
                sessions.unregister(Sessions.FROM_PREPR, preprocessor_id)
                self.cprv.preprocessor_ready(preprocessor_id)

        csrv = ClientServerRendezvous(self.timer, sessions, node_info, cprv)

        try:
            while True:
                self.print_stats(node_info)
                node_connections = node_manager.spawn_connections()
                for connection in node_connections:
                    register_socket(connection)

                sockets = dict(poller.poll(1000))
                for socket, flags in sockets.items():
                    if flags != zmq.POLLIN:
                        continue

                    elif socket is preprocess_socket:
                        with self.timer.timeit('poller.preprocess'):
                            msg = preprocess_socket.recv_multipart()
                            preprocessor_id = msg[0]
                            if msg[1] == b'PREPROCESSOR_READY':
                                cprv.preprocessor_ready(preprocessor_id)
                            else:
                                session = sessions.get(Sessions.FROM_PREPR, preprocessor_id)
                                if session:
                                    assert msg[1] == b'PREPROCESSING_DONE'
                                    self.timer.add_time('preprocessing', pickle.loads(msg[2]))
                                    csrv.client_ready((session, preprocessor_id, SimpleTimer()))
                                    server_result = node_manager.get_server_conn()
                                    if server_result:
                                        csrv.server_ready(server_result)
                    elif socket is client_socket:
                        with self.timer.timeit('poller.client'):
                            msg = client_socket.recv_multipart()
                            client_id = msg[0]
                            assert len(msg) == 2
                            assert msg[1][-2:] == b'\x00\x01'
                            parts = msg[1][:-2].split(b'\x00')
                            session = sessions.get(Sessions.FROM_CLIENT, client_id)
                            if session:
                                session.got_data_from_client(parts)
                            else:
                                # Create new session.
                                compiler_name = parts[0].decode()
                                executable = parts[1].decode()
                                sysincludes = parts[2].decode()
                                cwd = parts[3].decode()
                                command = [x.decode() for x in parts[4:]]
                                client_conn = self.SendProxy(client_socket, client_id)
                                client_conn.send([b'TASK_RECEIVED'])
                                assert compiler_name == 'msvc'
                                compiler = MSVCWrapper()
                                for task in create_tasks(client_conn, compiler,
                                    executable, cwd, sysincludes, command):
                                    cprv.client_ready((compiler, executable, task,
                                        client_conn, SimpleTimer()))
                    else:
                        with self.timer.timeit('poller.server'):
                            # Connection to server node.
                            result = sessions.get(Sessions.FROM_SERVER, socket)
                            if result is not None:
                                # Part of a session.
                                session, node_index = result
                                msg = socket.recv_multipart()
                                client_id = session.client_conn.id
                                session_done = session.got_data_from_server(msg)
                                if session_done:
                                    sessions.unregister(Sessions.FROM_SERVER, socket)
                                    sessions.unregister(Sessions.FROM_CLIENT, client_id)
                                    unregister_socket(socket)
                                    node_manager.recycle(node_index, socket)
                            else:
                                # Not part of a session, handled by node_manager.
                                node_index = node_manager.handle_socket(socket)
                                if node_index is not None and csrv.has_first():
                                    server_conn, node_index = node_manager.get_server_conn(node_index)
                                    assert server_conn
                                    csrv.server_ready((server_conn, node_index))
        finally:
            for scan_worker in scan_workers:
                scan_worker.terminate()

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
        for index in range(len(node_info)):
            node = node_info[index]
            times = node.timer().as_dict()
            if not times:
                continue
            print("================")
            print("Statistics for '{}'".format(node.node_dict()['address']))
            print("================")
            print_times(times)
        return True
