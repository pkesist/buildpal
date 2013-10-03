from .compile_session import CompileSession
from .node_info import NodeInfo
from .source_scanner import SourceScanner
from .timer import Timer

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
        self.__unique_id = 0

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
            except zmq.ZMQError:
                print("Failed to connect to '{}'".format(node))
                return None
        socket.send(b'CREATE_SESSION')
        return socket

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

        scan_workers = [SourceScanner(preprocess_socket_port, timer, self.__nodes) for i in range(cpu_count() * 2)]
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
                        if not socket:
                            break
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
                                if nodes_waiting.get(node_index):
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
