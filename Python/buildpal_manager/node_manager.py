from .compile_session import CompileSession, SessionResult
from .compressor import Compressor

from buildpal_common import MessageProtocol

import asyncio
import logging
import struct

from concurrent.futures import ThreadPoolExecutor
from math import floor
from collections import defaultdict
from queue import Queue, Empty
from time import time
from .gui_event import GUIEvent

class NodeManager:
    def __init__(self, loop, node_info, update_ui):
        self.loop = loop
        self.node_info = node_info
        self.update_ui = update_ui
        self.all_sockets = defaultdict(list)
        self.tasks_running = defaultdict(list)
        self.sessions = {}
        self.unassigned_tasks = []
        self.executor = ThreadPoolExecutor(2)
        self.compressor = Compressor(self.loop, self.executor)
        self.counter = 0

    def task_preprocessed(self, task, exception=None):
        if exception:
            logging.error("Preprocessing failure: %s", exception)
            def task_error():
                task.task_completed(-1, b'', 'BUILDPAL ERROR: {}\n'.format(exception).encode())
            self.loop.call_soon_threadsafe(task_error)
            return

        logging.debug("Headers for file '%s':", task.source)
        for dir, data in task.header_info:
            logging.debug(dir)
            for file, relative, content, checksum in data:
                logging.debug("    %s %s", file, "relative to source" if relative else "")
                if file[:2] == '..' and not relative:
                    logging.debug("Cannot distribute task: Uses a header outside include directory: '%s'\n", file)
                    task.cannot_distribute()
                    return

        if task.missing_headers:
            error = "BUILDPAL ERROR: Cannot compile '{}' due to missing headers:\n".format(
                task.source)
            missing_headers = str()
            for h in task.missing_headers:
                missing_headers += "    {}\n".format(h)
            logging.debug("Compile failure: Missing headers\n%s", missing_headers)
            task.task_completed('-1', b'', (error + missing_headers).encode())
            return
        def schedule_task(task):
            task.note_time('collected from preprocessor', 'preprocessed notification time')
            self.schedule_task(task)
        self.loop.call_soon_threadsafe(schedule_task, task)

    def schedule_task(self, task, node=None):
        if node is not None:
            self.tasks_running[node].append(task)
        elif self.unassigned_tasks:
            self.unassigned_tasks.append(task)
            self.update_ui(GUIEvent.update_unassigned_tasks,
                len(self.unassigned_tasks))
            return
        asyncio.async(self.__get_server_conn(node), loop=self.loop
            ).add_done_callback(lambda f : self.create_session(task, node, f))

    def create_session(self, task, predetermined_node, future):
        result = future.result()
        if result is None:
            self.unassigned_tasks.append(task)
            self.update_ui(GUIEvent.update_unassigned_tasks,
                len(self.unassigned_tasks))
            return
        protocol, node = result
        session = CompileSession(self.generate_unique_id(), task,
            protocol.send_msg, node, self.executor, self.compressor)
        self.sessions[session.local_id] = session
        if not predetermined_node:
            self.tasks_running[node].append(task)
        else:
            assert task in self.tasks_running[node]
            assert node == predetermined_node
        session.start()
        self.update_ui(GUIEvent.update_node_info, self.node_info)

    def generate_unique_id(self):
        self.counter += 1
        return struct.pack('!I', self.counter)

    def protocol_factory(self):
        protocol = MessageProtocol()
        protocol.process_msg = self.process_msg
        return protocol

    @asyncio.coroutine
    def __connect_to_node(self, node):
        (transport, protocol) = yield from self.loop.create_connection(
            self.protocol_factory, host=node.node_dict()['address'],
            port=node.node_dict()['port'])
        self.all_sockets[node].append((transport, protocol))

    def close(self):
        self.executor.shutdown()
        for node, ptlist in self.all_sockets.items():
            for transport, protocol in ptlist:
                transport.abort()
            
    def __target_tasks_per_node(self, node):
        return node.node_dict()['job_slots'] + 1

    def __can_steal_task(self, node):
        return len(self.tasks_running[node]) < node.node_dict()['job_slots']

    def __free_slots(self, node):
        return self.__target_tasks_per_node(node) - len(self.tasks_running[node])

    def __tasks_viable_for_stealing(self, src_node, tgt_node):
        if src_node.average_task_time() == 0:
            return []
        if tgt_node.average_task_time() == 0:
            return []
        task_index = floor(tgt_node.average_task_time() /
            src_node.average_task_time()) * src_node.node_dict()['job_slots']
        return self.tasks_running[src_node][task_index:]

    def __best_node(self):
        def current_node_weight(node):
            return (len(self.tasks_running[node]) * node.average_task_time(),
                node.average_task_time())
        free_nodes = [node for node in self.node_info if self.__free_slots(node) > 0]
        if not free_nodes:
            return None
        return min(free_nodes, key=current_node_weight)

    def __steal_tasks(self, node):
        tasks_to_steal = self.__free_slots(node)
        while tasks_to_steal > 0:
            while self.unassigned_tasks:
                task = self.unassigned_tasks.pop(0)
                self.update_ui(GUIEvent.update_unassigned_tasks,
                    len(self.unassigned_tasks))
                task.note_time('taken from unassigned task queue', 'unassigned time')
                self.schedule_task(task, node)
                tasks_to_steal -= 1
                if tasks_to_steal == 0:
                    return
            if not self.__can_steal_task(node):
                return
            for from_node in self.tasks_running:
                if node == from_node:
                    continue
                for task in reversed(self.__tasks_viable_for_stealing(from_node, node)):
                    if not task.is_completed() and task not in self.tasks_running[node]:
                        self.schedule_task(task, node)
                        tasks_to_steal -= 1
                        if tasks_to_steal <= 0:
                            return
            return

    @asyncio.coroutine
    def __get_server_conn(self, node):
        if not node:
            node = self.__best_node()
        if not node:
            return None
        node_sockets = self.all_sockets[node]
        if not node_sockets:
            yield from self.__connect_to_node(node)
        assert node_sockets
        return node_sockets[0][1], node

    def process_msg(self, msg):
        session_id, *msg = msg
        session = self.sessions.get(session_id)
        if not session:
            return
        if not session.got_data_from_server(msg):
            return
        del self.sessions[session_id]
        self.tasks_running[session.node].remove(session.task)
        self.__steal_tasks(session.node)
        # In case we got a server failure, reschedule the task.
        if session.result in (SessionResult.failure, SessionResult.timed_out) \
            and not session.task.is_completed() and \
            len(session.task.sessions_running) == 1:
                self.schedule_task(session.task)
        session.task.session_completed(session)
        self.update_ui(GUIEvent.update_node_info, self.node_info)
