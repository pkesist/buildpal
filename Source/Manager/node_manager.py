import pickle
import zmq

from functools import cmp_to_key
from struct import pack

from Common import create_socket, recv_multipart

class NodeManager:
    def __init__(self, node_info):
        self.sockets_ready = {}
        self.node_info = node_info

    def __connect_to_node(self, zmq_ctx, node_index, register):
        node_address = self.node_info[node_index].node_dict()['address']
        try:
            socket = create_socket(zmq_ctx, zmq.DEALER)
            socket.connect(node_address)
            register(socket)
        except zmq.ZMQError:
            print("Failed to connect to '{}'".format(node_address))
            raise Exception("Invalid node")
        self.sockets_ready.setdefault(node_index, []).append(socket)
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
        self.sockets_ready[node_index].append(socket)

    def close(self):
        for node_index, node_sockets in self.sockets_ready.items():
            node_address = self.node_info[node_index].node_dict()['address']
            for socket in node_sockets:
                socket.close()

    def get_server_conn(self, zmq_ctx, register):
        node_index = self.__best_node()
        node_sockets = self.sockets_ready.setdefault(node_index, [])
        if len(node_sockets) <= 1:
            self.__connect_to_node(zmq_ctx, node_index, register), node_index
        assert node_sockets
        return node_sockets.pop(0), node_index
