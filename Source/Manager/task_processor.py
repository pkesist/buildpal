from Compilers import MSVCWrapper
from Common import SimpleTimer, recv_multipart, create_socket

from .source_scanner import SourceScanner
from .command_processor import CommandProcessor
from .timer import Timer
from .node_manager import NodeManager
from .console import ConsolePrinter
from .node_info import NodeInfo

from Common import bind_to_random_port

import operator
import pickle
import sys
import zmq
import sched
import selectors
import socket
import threading

from multiprocessing import cpu_count
from time import time
from subprocess import list2cmdline

class ClientProcessor:
    def __init__(self, socket, compiler_info, task_created_func, register,
            unregister, ui_data):
        self.socket = socket
        self.compiler_info = compiler_info
        self.data = b''
        self.task_created_func = task_created_func
        self.unregister = unregister
        register(self.socket, selectors.EVENT_READ, self.read)
        self.registered = True
        self.ui_data = ui_data

    def close(self):
        if self.registered:
            self.unregister(self.socket)
            self.registered = False
        self.socket.close()

    def send(self, data):
        try:
            self.socket.sendall(b'\x00'.join(data) + b'\x00\x01')
        except ConnectionResetError:
            self.close()

    def read(self, sock):
        assert sock == self.socket
        data = sock.recv(1024)
        self.data = self.data + data
        while True:
            msg = self.__get_message()
            if msg is not None:
                self.__handle_message(msg)
            else:
                break

    def __get_message(self):
        try:
            end_index = self.data.index(b'\x00\x01')
        except ValueError:
            return None
        result = self.data[:end_index].split(b'\x00')
        self.data = self.data[end_index + 2:]
        return result

    def __handle_message(self, msg):
        if hasattr(self, 'cmd_processor'):
            self.cmd_processor.got_data_from_client(msg)
        else:
            self.__handle_new_client(msg)

    def __handle_new_client(self, msg):
        compiler_name = msg[0].decode()
        executable = msg[1].decode()
        sysincludes = msg[2].decode()
        cwd = msg[3].decode()
        command = [x.decode() for x in msg[4:]]
        assert compiler_name == 'msvc'
        compiler = MSVCWrapper()
        self.cmd_processor = CommandProcessor(self, executable,
            cwd, sysincludes, compiler, command, self.ui_data)

        if self.cmd_processor.build_local():
            self.send([b'EXECUTE_AND_EXIT', list2cmdline(command).encode()])
            self.close()
            return True

        if executable in self.compiler_info:
            info, files = self.compiler_info[executable]
            self.cmd_processor.set_compiler_info(info, files)
            self.__create_tasks()
        else:
            self.cmd_processor.request_compiler_info(on_completion=self.__create_tasks)

    def __create_tasks(self):
        # No more data will be read from the client.
        if self.registered:
            self.unregister(self.socket)
            self.registered = False
        assert self.cmd_processor.state == self.cmd_processor.STATE_HAS_COMPILER_INFO
        if not self.cmd_processor.executable() in self.compiler_info:
            self.compiler_info[self.cmd_processor.executable()] = \
                self.cmd_processor.compiler_info, self.cmd_processor.compiler_files
        for task in self.cmd_processor.create_tasks():
            task.server_task_info['compiler_info'] = task.compiler_info()
            task.preprocess_task_info['macros'].extend(
                task.compiler_info()['macros'])
            task.pp_timer = SimpleTimer()
            self.task_created_func(task)

class TaskProcessor:
    def __init__(self, nodes, port, n_pp_threads, ui_data):
        class CacheStats:
            def __init__(self):
                self.hits = 0
                self.misses = 0
                self.ratio = 0.0

            def update(self, data):
                self.hits, self.misses = data
                total = self.hits + self.misses
                if total == 0:
                    total = 1
                self.ratio = self.hits / total

        self.port = port
        self.compiler_info = {}
        self.timer = Timer()
        self.node_info = [NodeInfo(nodes[x], x) for x in range(len(nodes))]

        self.n_pp_threads = n_pp_threads
        if not self.n_pp_threads:
            self.n_pp_threads = cpu_count()

        self.ui_data = ui_data
        self.ui_data.timer = self.timer
        self.ui_data.node_info = self.node_info
        self.ui_data.cache_stats = CacheStats()

    def client_thread(self, task_created_func):
        client_selector = selectors.DefaultSelector()

        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.bind(('', self.port))
        listen_socket.listen(16)
        
        def accept(sock):
            conn, addr = sock.accept()
            conn.setblocking(False)
            client_processor = ClientProcessor(conn, self.compiler_info,
                task_created_func, client_selector.register,
                client_selector.unregister, self.ui_data)

        client_selector.register(listen_socket, selectors.EVENT_READ, accept)
        while True:
            for key, mask in client_selector.select(1):
                callback = key.data
                callback(key.fileobj)
            if self.terminating:
                break
        listen_socket.close()

    def run(self, observer=None):
        self.terminating = False
        zmq_ctx = zmq.Context()
        self.node_manager = NodeManager(self.node_info)
        source_scanner = SourceScanner(self.node_manager.task_ready, self.n_pp_threads)

        self.client_thread = threading.Thread(target=self.client_thread,
            kwargs={'task_created_func' : source_scanner.add_task})
        self.client_thread.start()

        try:
            if observer is None:
                observer = ConsolePrinter(self.node_info, self.ui_data)
            self.node_manager.run(observer)
        finally:
            self.terminating = True
            self.client_thread.join()
            source_scanner.close()
            self.node_manager.close()

    def stop(self):
        self.node_manager.stop()
