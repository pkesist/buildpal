from .compile_session import CompileSession, SessionResult
from .poller import ZMQSelectPoller

import pickle
import zlib
import zmq
import queue

from functools import cmp_to_key
from io import BytesIO
from math import floor
from struct import pack
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import time

from Common import create_socket, recv_multipart

Poller = ZMQSelectPoller

class Compressor:
    def __init__(self, poller):
        self.executor = ThreadPoolExecutor(2)
        self.poller = poller
        self.compressed_files = []
        self.compressed_file_data = {}
        self.mylock = Lock()
        self.waiters = defaultdict(list)

    def compress(self, file, on_completion):
        self.mylock.acquire()
        if file in self.compressed_files:
            self.mylock.release()
            on_completion(BytesIO(self.compressed_file_data[file]))
        else:
            try:
                if file not in self.waiters:
                    event = self.poller.create_event(lambda ev : self.__compression_completed(file, ev))
                    self.executor.submit(self.__do_compress, file).add_done_callback(lambda f : event())
                self.waiters.setdefault(file, []).append(on_completion)
            finally:
                self.mylock.release()

    def __compression_completed(self, file, event):
        event.close()
        for on_completion in self.waiters[file]:
            on_completion(BytesIO(self.compressed_file_data[file]))
        del self.waiters[file]

    def __do_compress(self, file):
        buffer = BytesIO()
        compressor = zlib.compressobj(1)
        with open(file, 'rb') as fileobj:
            for data in iter(lambda : fileobj.read(256 * 1024), b''):
                buffer.write(compressor.compress(data))
        buffer.write(compressor.flush())
        buffer.seek(0)
        with self.mylock:
            if len(self.compressed_file_data) > 4:
                del self.compressed_file_data[self.compressed_files.pop(0)]
            self.compressed_files.append(file)
            self.compressed_file_data[file] = buffer.read()

class NodeManager:
    def __init__(self, node_info):
        self.zmq_ctx = zmq.Context()
        self.poller = Poller(self.zmq_ctx)
        self.task_ready_event = self.poller.create_event(
            self.__process_input_tasks)
        self.input_tasks = queue.Queue()
        self.node_info = node_info
        self.all_sockets = defaultdict(list)
        self.sockets_ready = defaultdict(list)
        self.tasks_running = defaultdict(list)
        self.sessions = {}
        self.unassigned_tasks = []
        self.compressor = Compressor(self.poller)

    def unassigned_tasks_count(self):
        return len(self.unassigned_tasks)

    def task_ready(self, task):
        self.input_tasks.put(task)
        self.task_ready_event()

    def run(self, observer):
        self.poller.run(observer)

    def stop(self):
        self.poller.stop()

    def __process_input_tasks(self, event):
        try:
            while True:
                task = self.input_tasks.get_nowait()
                task.note_time('collected from preprocessor')
                self.schedule_task(task)
        except queue.Empty:
            pass

    def schedule_task(self, task, node=None):
        if node is None and self.unassigned_tasks:
            task.note_time('queue as unassigned task')
            self.unassigned_tasks.append(task)
            return
        result = self.__get_server_conn(node)
        if result is None:
            assert node is None
            task.note_time('queue as unassigned task')
            self.unassigned_tasks.append(task)
            return
        server_conn, node = result
        session = CompileSession(task, server_conn, node, self.compressor)
        self.sessions[server_conn] = session
        self.tasks_running[node].append(task)
        session.start()

    def close(self):
        for node, socketlist in self.all_sockets.items():
            for socket in socketlist:
                self.poller.unregister(socket)
                socket.close()
        self.poller.close()
        self.zmq_ctx.term()

    def __connect_to_node(self, node):
        node_address = node.zmq_address()
        try:
            socket = create_socket(self.zmq_ctx, zmq.DEALER)
            socket.connect(node_address)
            self.poller.register(socket, self.__handle_server_socket)
        except zmq.ZMQError:
            print("Failed to connect to '{}'".format(node_address))
            raise Exception("Invalid node")
        self.sockets_ready[node].append(socket)
        self.all_sockets[node].append(socket)
        return socket
            
    def __target_tasks_per_node(self, node):
        return node.node_dict()['job_slots'] + 1

    def __can_steal_task(self, node):
        return len(self.tasks_running[node]) < node.node_dict()['job_slots']

    def __free_slots(self, node):
        return self.__target_tasks_per_node(node) - len(self.tasks_running[node])

    def __tasks_viable_for_stealing(self, src_node, tgt_node):
        if src_node.average_task_time() == 0:
            return self.tasks_running[src_node]
        if tgt_node.average_task_time() == 0:
            return self.tasks_running[src_node]
        task_index = floor(tgt_node.average_task_time() / src_node.average_task_time()) * src_node.node_dict()['job_slots']
        return self.tasks_running[src_node][task_index:]

    def __best_node(self):
        def current_node_weight(node):
            return (len(self.tasks_running[node]) * node.average_task_time(),
                node.average_task_time())
        nodes = self.node_info[:]
        nodes.sort(key=current_node_weight)
        for node in nodes:
            if node.average_task_time() == 0:
                if len(self.tasks_running[node]) < self.__target_tasks_per_node(node):
                    return node
            elif self.__free_slots(node) > 0:
                return node
        return None

    def __steal_tasks(self, node):
        tasks_to_steal = self.__free_slots(node)
        while tasks_to_steal > 0:
            while self.unassigned_tasks:
                task = self.unassigned_tasks.pop(0)
                task.note_time('taken from unassigned task queue')
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

    def __get_server_conn(self, node):
        if not node:
            node = self.__best_node()
        if not node:
            return None
        node_sockets = self.sockets_ready[node]
        if len(node_sockets) <= 1:
            self.__connect_to_node(node)
        assert node_sockets
        return node_sockets.pop(0), node

    def __handle_server_socket(self, socket, msg):
        session = self.sessions.get(socket)
        if not session:
            print("Got data for non-session")
            print([m.tobytes()[:50] for m in msg])
            return
        session_result = session.got_data_from_server(msg)
        if session_result is None:
            return
        assert session.state == session.STATE_FINISH
        session.time_completed = time()
        del self.sessions[socket]
        task = session.task
        node = session.node
        self.sockets_ready[node].append(socket)
        self.tasks_running[node].remove(task)
        self.__steal_tasks(node)
        if session_result == SessionResult.success:
            node.timer().add_time("session duration", session.time_completed - session.time_started)
            task.completed(session, session.retcode,
                session.stdout, session.stderr)
        elif session_result == SessionResult.failure:
            task.failed(session)
            if task.is_completed():
                assert task.session_completed != session
                return
            if not task.sessions_running:
                self.schedule_task(task)
        elif session_result == SessionResult.cancelled:
            task.cancelled(session)
        elif session_result == SessionResult.timed_out:
            task.timed_out(session)
        elif session.state == SessionResult.too_late:
            task.too_late(session)
        else:
            assert not "Invalid session result"
