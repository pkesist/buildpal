import pickle
import zmq

from functools import cmp_to_key
from struct import pack

from Common import create_socket, recv_multipart

class NodeManager:
    def __init__(self, zmq_ctx, node_info, register, unregister):
        self.zmq_ctx = zmq_ctx
        self.node_info = node_info
        self.register_socket = register
        self.unregister_socket = unregister
        self.all_sockets = set()
        self.sockets_ready = {}

    def __connect_to_node(self, node):
        node_address = node.zmq_address()
        try:
            socket = create_socket(self.zmq_ctx, zmq.DEALER)
            socket.connect(node_address)
            self.register_socket(socket)
        except zmq.ZMQError:
            print("Failed to connect to '{}'".format(node_address))
            raise Exception("Invalid node")
        self.sockets_ready.setdefault(node, []).append(socket)
        self.all_sockets.add(socket)
        return socket
            
    def __best_node(self):
        def cmp(lhs_node, rhs_node):
            lhs_tasks_pending = lhs_node.tasks_pending()
            rhs_tasks_pending = rhs_node.tasks_pending()

            def time_per_task(node):
                timer = node.timer().as_dict()
                hl_total, hl_count = timer.get('server.wait_for_header_list', (0, 1))
                h_total, h_count = timer.get('server.wait_for_headers', (0, 1))
                return node.average_task_time() - hl_total / hl_count + h_total / h_count

            lhs_time_per_task = time_per_task(lhs_node)
            rhs_time_per_task = time_per_task(rhs_node)

            if lhs_time_per_task == 0 and rhs_time_per_task == 0:
                return -1 if lhs_tasks_pending < rhs_tasks_pending else 1
            if lhs_tasks_pending == 0 and rhs_tasks_pending == 0:
                return -1 if lhs_time_per_task < rhs_time_per_task else 1
            # In case we don't yet have average time per task for a node, do
            # not allow that node to be flooded.
            if lhs_time_per_task == 0 and lhs_tasks_pending >= 5:
                return 1
            return -1 if lhs_tasks_pending * lhs_time_per_task <= rhs_tasks_pending * rhs_time_per_task else 1
        return min(self.node_info, key=cmp_to_key(cmp))

    def recycle(self, node, socket):
        self.sockets_ready[node].append(socket)

    def close(self):
        for socket in self.all_sockets:
            self.unregister_socket(socket)
            socket.close()

    def get_server_conn(self):
        node = self.__best_node()
        node_sockets = self.sockets_ready.setdefault(node, [])
        if len(node_sockets) <= 1:
            self.__connect_to_node(node)
        assert node_sockets
        return node_sockets.pop(0), node
