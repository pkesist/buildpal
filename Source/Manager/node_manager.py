import pickle
import zmq

from functools import cmp_to_key
from struct import pack

from Common import create_socket

class NodeManager:
    STATE_SOCKET_OPEN = 0
    STATE_SOCKET_RESPONDED = 1
    STATE_SOCKET_READY = 2

    CONNECTIONS_PER_NODE = 16

    def __init__(self, node_info):
        self.sockets_registered = {}
        self.sockets_ready = {}
        self.sockets_requested = {}
        self.sockets_recycled = {}
        self.node_info = node_info
        self.__unique_id = 0

    def spawn_connections(self, zmq_ctx):
        result = []
        for node_index in range(len(self.node_info)):
            for x in range(self.CONNECTIONS_PER_NODE - self.__node_connections(node_index)):
                socket = self.__connect_to_node(zmq_ctx, node_index)
                if not socket:
                    break
                result.append(socket)
        return result

    def __connect_to_node(self, zmq_ctx, node_index):
        recycled = self.sockets_recycled.get(node_index)
        if recycled:
            socket = recycled[0]
            del recycled[0]
        else:
            node_address = self.node_info[node_index].node_dict()['address']
            try:
                socket = create_socket(zmq_ctx, zmq.DEALER)
                socket.setsockopt(zmq.IDENTITY, b'A' + pack('>I', self.__unique_id))
                self.__unique_id += 1
                socket.connect(node_address)
            except zmq.ZMQError:
                print("Failed to connect to '{}'".format(node_address))
                return None
        socket.send(b'CREATE_SESSION')
        self.__register(socket, node_index)
        return socket
            
    def __best_node(self):
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
        return min(range(len(self.node_info)), key=cmp_to_key(cmp))

    def recycle(self, node_index, socket):
        recycled = self.sockets_recycled.setdefault(
            node_index, [])
        old_len = len(self.sockets_recycled[node_index])
        assert socket not in recycled
        recycled.append(socket)
        assert len(self.sockets_recycled[node_index]) == old_len + 1

    def __register(self, socket, node_index):
        self.sockets_registered[socket] = (node_index, self.STATE_SOCKET_OPEN)
        self.sockets_requested[node_index] = self.sockets_requested.get(node_index, 0) + 1

    def get_server_conn(self, node_index=None):
        if node_index is None:
            node_index = self.__best_node()
        if node_index is None:
            return None
        node_sockets = self.sockets_ready.get(node_index)
        if not node_sockets:
            return None
        socket = node_sockets[0]
        del node_sockets[0]
        del self.sockets_registered[socket]
        return socket, node_index

    def __node_connections(self, node_index):
        return self.sockets_requested.get(node_index, 0) + \
            len(self.sockets_ready.get(node_index, []))

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
                # Add it to the recycled list.
                self.sockets_recycled[node_index].append(socket)
                return None
