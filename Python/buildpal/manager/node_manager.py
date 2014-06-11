from .compile_session import ServerSession, SessionResult
from .compressor import Compressor

from buildpal.common import MessageProtocol

import asyncio
import logging
import struct

from concurrent.futures import ThreadPoolExecutor
from math import floor
from collections import defaultdict
from time import time
from .gui_event import GUIEvent

class NodeManager:
    def __init__(self, loop, node_info_getter, update_ui):
        self.loop = loop
        self.node_info_getter = node_info_getter
        self.node_info = []
        self.update_ui = update_ui
        self.all_sockets = defaultdict(list)
        self.tasks_running = defaultdict(list)
        self.sessions = {}
        self.unassigned_tasks = []
        self.executor = ThreadPoolExecutor(2)
        self.compressor = Compressor(self.loop, self.executor)
        self.counter = 0
        self.update_node_info()

    def update_node_info(self):
        asyncio.async(self.update_node_info_coro(), loop=self.loop)

    def get_node_info(self):
        return self.node_info

    @asyncio.coroutine
    def update_node_info_coro(self):
        new_node_info = self.node_info_getter()
        sessions_to_reschedule = []
        for node in (node for node in self.node_info if node not in new_node_info):
            for session in self.sessions.values():
                if session.node == node:
                    sessions_to_reschedule.append(session)
        new_nodes = [node for node in new_node_info if node not in self.node_info]
        self.node_info = new_node_info
        for session in sessions_to_reschedule:
            session.terminate()
        for node in new_nodes:
            self.__find_work(node)
        self.update_ui(GUIEvent.update_node_info, self.node_info)
        yield from asyncio.sleep(2, loop=self.loop)
        self.update_node_info()

    def task_preprocessed(self, task, exception=None):
        if exception:
            logging.exception(exception)
            def task_error():
                task.task_completed(-1, b'', 'BUILDPAL ERROR: {}\n'.format(exception).encode())
            self.loop.call_soon_threadsafe(task_error)
            return

        logging.debug("Headers for file '%s':", task.source)
        for dir, system, data in task.header_info:
            logging.debug(dir)
            for file, relative, content, checksum in data:
                logging.debug("    %s %s", file, "[relative to source]" if relative else "")

        if task.missing_headers:
            error = "BUILDPAL ERROR: Cannot compile '{}' due to missing headers:\n".format(
                task.source)
            missing_headers = str()
            for h in task.missing_headers:
                missing_headers += "    {}\n".format(h)
            logging.debug("Compile failure: Missing headers\n%s", missing_headers)
            task.task_completed(-1, b'', (error + missing_headers).encode())
            return
        task.note_time('collected from preprocessor', 'preprocessed notification time')
        self.loop.call_soon_threadsafe(self.schedule_task, task)

    def __schedule_task_to_specific_node(self, task, node):
        assert node is not None
        asyncio.async(self.__get_server_conn(node), loop=self.loop
            ).add_done_callback(lambda f : self.create_session(task, f))

    def schedule_task(self, task, high_priority=False):
        add_to_queue = False
        if self.unassigned_tasks:
            add_to_queue = True
        else:
            node = self.__best_node()
            if node is None:
                add_to_queue = True

        if add_to_queue:
            if high_priority:
                self.unassigned_tasks.insert(0, task)
            else:
                self.unassigned_tasks.append(task)
            self.update_ui(GUIEvent.update_unassigned_tasks,
                len(self.unassigned_tasks))
        else:
            self.__schedule_task_to_specific_node(task, node)

    def create_session(self, task, future):
        protocol, node = future.result()
        def async_call(callable, *args):
            return self.loop.run_in_executor(self.executor, callable, *args)

        def session_completed(session):
            del self.sessions[session.local_id]
            self.tasks_running[session.node].remove(session.task)
            self.__find_work(session.node)
            if not session.task.session_completed(session):
                # Give the task high priority.
                self.schedule_task(session.task, high_priority=True)
            self.update_ui(GUIEvent.update_node_info, self.node_info)

        session = ServerSession(self.__generate_unique_id(), task,
            protocol.send_msg, node, async_call, self.compressor,
            session_completed)
        self.tasks_running[node].append(task)
        self.sessions[session.local_id] = session
        session.start()
        self.update_ui(GUIEvent.update_node_info, self.node_info)

    def __generate_unique_id(self):
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
            task_count = len(self.tasks_running[node])
            average_time = node.average_task_time()
            return (task_count * average_time, average_time, task_count)
        free_nodes = [node for node in self.node_info if self.__free_slots(node) > 0]
        if not free_nodes:
            return None
        return min(free_nodes, key=current_node_weight)

    def __find_work(self, node):
        available_slots = self.__free_slots(node)
        while available_slots > 0:
            while self.unassigned_tasks:
                task = self.unassigned_tasks.pop(0)
                self.update_ui(GUIEvent.update_unassigned_tasks,
                    len(self.unassigned_tasks))
                task.note_time('taken from unassigned task queue', 'unassigned time')
                self.__schedule_task_to_specific_node(task, node)
                available_slots -= 1
                if available_slots == 0:
                    return
            if not self.__can_steal_task(node):
                return
            for from_node in self.tasks_running:
                if node == from_node:
                    continue
                for task in reversed(self.__tasks_viable_for_stealing(from_node, node)):
                    if not task.is_completed() and task not in self.tasks_running[node]:
                        self.__schedule_task_to_specific_node(task, node)
                        available_slots -= 1
                        if available_slots <= 0:
                            return
            return

    @asyncio.coroutine
    def __get_server_conn(self, node):
        assert node
        node_sockets = self.all_sockets[node]
        if not node_sockets:
            yield from self.__connect_to_node(node)
        assert node_sockets
        return node_sockets[0][1], node

    def process_msg(self, msg):
        session_id, *msg = msg
        session = self.sessions.get(session_id)
        if session:
            session.got_data_from_server(msg)
