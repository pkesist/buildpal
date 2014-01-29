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
import select
import socket
import threading

from functools import cmp_to_key
from multiprocessing import cpu_count, Semaphore
from socket import getfqdn
from time import time

class PollingMechanism:
    ZMQ_SELECT = 0
    OS_SELECT = 1
    ASYNCIO_PROACTOR = 2

polling_mechanism = PollingMechanism.ZMQ_SELECT

if polling_mechanism == PollingMechanism.OS_SELECT:
    class ZmqSocket:
        def __init__(self, timer, socket, handler):
            self.socket = socket
            self.handler = handler
            self.timer = timer

        @classmethod
        def fileno_from_socket(cls, sock):
            return sock.getsockopt(zmq.FD)

        def fileno(self):
            return self.fileno_from_socket(self.socket)

        def registered(self):
            while True:
                try:
                    self.handler(self.socket, recv_multipart(self.socket, zmq.NOBLOCK))
                except zmq.ZMQError:
                    return

        def ready(self):
            if self.socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
                self.registered()

    class RawSocket:
        def __init__(self, timer, socket, handler):
            self.socket = socket
            self.handler = handler
            self.timer = timer

        def registered(self):
            pass

        @classmethod
        def fileno_from_socket(cls, sock):
            return sock.fileno()

        def fileno(self):
            return self.fileno_from_socket(self.socket)

        def ready(self):
            self.handler(self.socket, self.socket.recv(256))

    class Poller:
        def __init__(self):
            self.pollin = set()
            self.pollout = set()
            self.sockets = {}

        def __wrap_type(self, sock):
            if isinstance(sock, zmq.Socket):
                return ZmqSocket
            elif isinstance(sock, socket.socket):
                return RawSocket

        def register(self, timer, socket, handler):
            self.register_worker(self.__wrap_type(socket)(timer, socket, handler))

        def register_worker(self, socket):
            fd = socket.fileno()
            self.sockets[fd] = socket
            self.pollin.add(fd)
            socket.registered()

        def unregister(self, socket):
            fd = self.__wrap_type(socket).fileno_from_socket(socket)
            self.pollin.discard(fd)
            self.sockets.pop(fd)

        def run_one(self, timeout):
            pollin, pollout, pollerr = select.select(self.pollin, [], [], timeout)
            for fd in pollin:
                self.sockets[fd].ready()

        def run(self, printer):
            while True:
                printer()
                self.run_one(1)

elif polling_mechanism == PollingMechanism.ZMQ_SELECT:
    class Poller:
        def __init__(self):
            self.poller = zmq.Poller()
            self.sockets = {}

        def register(self, timer, socket, handler):
            self.sockets[socket] = handler, timer
            self.poller.register(socket, zmq.POLLIN)

        def unregister(self, socket):
            del self.sockets[socket]
            self.poller.unregister(socket)

        def run_one(self, timeout):
            result = self.poller.poll(timeout * 1000)
            for socket, event in result:
                assert event == zmq.POLLIN
                handler, timer = self.sockets[socket]
                handler(socket, recv_multipart(socket, zmq.NOBLOCK))

        def run(self, printer):
            while True:
                printer()
                self.run_one(1)

elif polling_mechanism == PollingMechanism.ASYNCIO_PROACTOR:
    import asyncio
    import socket
    import asyncio.windows_utils as asyncio_win
    import _overlapped

    class SocketWrapper:
        def __init__(self, fileno):
            self._fileno = fileno

        def fileno(self):
            return self._fileno

    class Poller:
        def __init__(self):
            self.proactor = asyncio.ProactorEventLoop()
            self.registered_sockets = set()

        @asyncio.coroutine
        def handle_socket(self, zmq_socket, handler, sock=None):
            assert zmq_socket in self.registered_sockets
            if sock is None:
                sock = SocketWrapper(fileno=zmq_socket.getsockopt(zmq.FD))
            tasks_handled = self.handle_tasks(zmq_socket, handler)
            yield from self.proactor.sock_recv(sock, 0)
            asyncio.async(self.handle_socket(zmq_socket, handler, sock), loop=self.proactor)

        def handle_tasks(self, socket, handler):
            assert socket in self.registered_sockets
            while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
                handler(socket, recv_multipart(socket, zmq.NOBLOCK))

        @asyncio.coroutine
        def handle_pipe(self, pipe_handle, handler):
            data = yield from self.proactor.sock_recv(pipe_handle, 256)
            handler(pipe_handle, data)
            asyncio.async(self.handle_pipe(pipe_handle, handler), loop=self.proactor)

        @asyncio.coroutine
        def print(self, printer):
            printer()
            yield from asyncio.sleep(2, loop=self.proactor)
            asyncio.async(self.print(printer), loop=self.proactor)

        def register_pipe(self, pipe_handle, handler):
            asyncio.async(self.handle_pipe(pipe_handle, handler), loop=self.proactor)

        def register(self, timer, socket, handler):
            assert socket not in self.registered_sockets
            self.registered_sockets.add(socket)
            asyncio.async(self.handle_socket(socket, handler), loop=self.proactor)

        def unregister(self, socket):
            """
            Did not really succeed implementing this.
            register->unregister->register sequence keeps crashing the process.
            Finally stopped using this pattern.
            """ 
            self.registered_sockets.remove(socket)

        def run(self, printer):
            asyncio.async(self.print(printer), loop=self.proactor)
            self.proactor.run_forever()


class TaskProcessor:
    class SendProxy:
        def __init__(self, socket, id):
            self.socket = socket
            self.id = id

        def send(self, data):
            try:
                self.socket.send_multipart(
                    [self.id, b'\x00'.join(data) + b'\x00\x01'], copy=False)
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

    class Sessions:
        FROM_CLIENT = 0
        FROM_SERVER = 1

        def __init__(self):
            self.session = {self.FROM_CLIENT : {}, self.FROM_SERVER : {}}

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
            try:
                del self.session[type][key]
            except Exception:
                import traceback
                traceback.print_exc()

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
            self.sessions.register(TaskProcessor.Sessions.FROM_SERVER, server_conn, session, node_index)
            session.preprocessing_done(server_conn, self.node_info[node_index])

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
            byte_data = data if type(data) == bytes else data.tobytes()
            self.data[client_id] = self.data.get(client_id, b'') + byte_data
            messages = []
            while True:
                x = self.__get_message(client_id)
                if x is not None:
                    messages.append(x)
                else:
                    break
            return messages

    def __init__(self, nodes, port):
        self.__port = port
        self.__nodes = nodes
        self.cache_info = (0, 0)
        self.compiler_info = {}
        self.timer = Timer()
        self.node_info = [NodeInfo(self.__nodes[x], x) for x in range(len(self.__nodes))]
        self.sessions = self.Sessions()
        self.node_manager = NodeManager(self.node_info)

        self.poller = Poller()

        self.zmq_ctx = zmq.Context()
        self.source_scanner = SourceScanner(self.notify_preprocessing_done)

        self.client_socket = create_socket(self.zmq_ctx, zmq.STREAM)
        self.client_socket.bind('tcp://*:{}'.format(self.__port))
        self.register_socket(self.client_socket, self.__handle_client_socket)

        self.csrv = self.ClientServerRendezvous(self.timer, self.sessions,
            self.node_info)
        self.client_data = self.ClientData()

    def register_socket(self, socket, handler):
        self.poller.register(self.timer, socket, handler)

    def unregister_socket(self, socket):
        self.poller.unregister(socket)

    def notify_preprocessing_done(self):
        if polling_mechanism == PollingMechanism.OS_SELECT:
            self.notify_socket.send(b'x')
        elif polling_mechanism == PollingMechanism.ZMQ_SELECT:
            notify_socket = create_socket(self.zmq_ctx, zmq.PAIR)
            notify_socket.connect('inproc://preprocessing')
            notify_socket.send(b'x')
            notify_socket.disconnect('inproc://preprocessing')
        elif polling_mechanism == PollingMechanism.ASYNCIO_PROACTOR:
            ov = _overlapped.Overlapped()
            ov.WriteFile(self.pp_pipe_write.fileno(), b'x')

    def __handle_preprocessing_done(self, socket, msg):
        fqdn = getfqdn()
        while True:
            result = self.source_scanner.completed_task()
            if not result:
                break
            client_id, header_info, time_in_in_queue, preprocessing_time, \
                time_queued, (hits, misses) = result
            time_in_out_queue = time() - time_queued
            self.cache_info = hits, misses
            session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
            assert(session)
            self.timer.add_time('preprocessing.in_queue', time_in_in_queue)
            self.timer.add_time('preprocessing.out_queue', time_in_out_queue)
            self.timer.add_time('preprocessing.internal', preprocessing_time)
            # Add filelist to package which goes to the server.
            session.task.server_task_info['filelist'] = create_filelist(header_info)
            session.task.server_task_info['fqdn'] = fqdn
            session.task.header_info = header_info
            session = self.sessions.get(self.Sessions.FROM_CLIENT,
                client_id)
            self.timer.add_time('preprocessing.external', session.pp_timer.get())
            DEBUG_just_preprocess = False
            if DEBUG_just_preprocess:
                session.client_conn.send([b'EXIT', b'0', b'', b''])
                self.sessions.unregister(self.Sessions.FROM_CLIENT, session.client_conn.id)
            else:
                self.csrv.client_ready((session, SimpleTimer()))
                server_result = self.node_manager.get_server_conn(self.zmq_ctx,
                    lambda socket : self.register_socket(socket,
                    self.__handle_server_socket))
                if server_result:
                    self.csrv.server_ready(server_result)

    def __handle_client_socket(self, socket, msg):
        client_id, data = msg
        messages = self.client_data.process_new_data(client_id, data)
        for msg in messages:
            session = self.sessions.get(self.Sessions.FROM_CLIENT, client_id)
            if session:
                session.got_data_from_client(msg)
            else:
                # Create new session.
                compiler_name = msg[0].decode()
                executable = msg[1].decode()
                sysincludes = msg[2].decode()
                cwd = msg[3].decode()
                command = [x.decode() for x in msg[4:]]
                client_conn = self.SendProxy(self.client_socket, client_id.tobytes())
                client_conn.send([b'TASK_RECEIVED'])
                assert compiler_name == 'msvc'
                compiler = MSVCWrapper()
                def preprocess_task(session):
                    session.pp_timer = SimpleTimer()
                    self.source_scanner.add_task(session.task)
                for task in create_tasks(client_conn, compiler,
                    executable, cwd, sysincludes, command):
                    session = CompileSession(task, preprocess_task,
                        self.compiler_info)
                    self.sessions.register(self.Sessions.FROM_CLIENT,
                        client_id, session)
                    session.begin()

    def __handle_server_socket(self, socket, msg):
        # Connection to server node.
        result = self.sessions.get(self.Sessions.FROM_SERVER, socket)
        if result is not None:
            # Part of a session.
            session, node_index = result
            client_id = session.client_conn.id
            session_done = session.got_data_from_server(msg)
            if session_done:
                self.sessions.unregister(self.Sessions.FROM_SERVER, socket)
                self.sessions.unregister(self.Sessions.FROM_CLIENT, client_id)
                self.node_manager.recycle(node_index, socket)
                if session.state == session.STATE_DONE:
                    session.task.completed(session.retcode,
                        session.stdout, session.stderr)
                else:
                    assert session.state == session.STATE_SERVER_FAILURE
                    if hasattr(task, 'retries'):
                        task.retries += 1
                    else:
                        task.retries = 1
                    if task.retries <= 3:
                        session.rewind()
                        self.csrv.client_ready((session, SimpleTimer()))
                        server_result = self.node_manager.get_server_conn(
                            self.zmq_ctx, lambda socket : self.register_socket(
                            socket, self.__handle_server_socket))
                        if server_result:
                            self.csrv.server_ready(server_result)
                    else:
                        session.task.completed(session.client_conn,
                            session.retcode, session.stdout, session.stderr)
        else:
            # Not part of a session, handled by node_manager.
            node_index = self.node_manager.handle_socket(socket, msg)
            if node_index is not None and self.csrv.first():
                register_func = lambda socket : self.register_socket(socket,
                    self.__handle_server_socket)
                server_conn, node_index = self.node_manager.get_server_conn(
                    self.zmq_ctx, register_func, node_index)
                assert server_conn
                self.csrv.server_ready((server_conn, node_index))

    def run(self):
        if polling_mechanism == PollingMechanism.OS_SELECT:
            listen_socket = socket.socket()
            listen_socket.bind(('', 50001))
            listen_socket.listen(0)

            self.notify_socket = socket.socket()
            self.notify_socket.connect(('localhost', 50001))

            self.preprocessing_done, whatever = listen_socket.accept()
            listen_socket.close()
            self.poller.register(self.timer, self.preprocessing_done, self.__handle_preprocessing_done)
        elif polling_mechanism == PollingMechanism.ZMQ_SELECT:
            self.preprocessing_done = create_socket(self.zmq_ctx, zmq.PAIR)
            self.preprocessing_done.bind('inproc://preprocessing')
            self.register_socket(self.preprocessing_done, self.__handle_preprocessing_done)
        elif polling_mechanism == PollingMechanism.ASYNCIO_PROACTOR:
            p1, p2 = asyncio_win.pipe()
            self.pp_pipe_read = asyncio_win.PipeHandle(p1)
            self.pp_pipe_write = asyncio_win.PipeHandle(p2)
            self.poller.register_pipe(self.pp_pipe_read, self.__handle_preprocessing_done)

        try:
            self.poller.run(self.print_stats)
        finally:
            self.source_scanner.terminate()
            if polling_mechanism == PollingMechanism.OS_SELECT:
                self.poller.unregister(self.preprocessing_done)
                self.preprocessing_done.close()
            elif polling_mechanism == PollingMechanism.ZMQ_SELECT:
                self.poller.unregister(self.preprocessing_done)
                self.preprocessing_done.unbind('inproc://preprocessing')
            elif polling_mechanism == PollingMechanism.ASYNCIO_PROACTOR:
                pass

    def print_stats(self):
        current_time = time()
        if hasattr(self, 'last_print') and (current_time - self.last_print) < 2:
            return
        self.last_print = current_time
        print("================")
        print("Build nodes:")
        print("================")
        for index in range(len(self.node_info)):
            node = self.node_info[index]
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
        print("in_queue_size {}".format(self.source_scanner.in_queue.qsize()))
        print("out_queue_size {}".format(self.source_scanner.out_queue.qsize()))
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
        for index in range(len(self.node_info)):
            node = self.node_info[index]
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


def create_filelist(header_info):
    result = []
    for dir, content in header_info:
        dir_data = []
        for file, relative, content, checksum, header in content:
            # Headers which are relative to source file are not
            # considered as candidates for server cache, and are
            # always sent together with the source file.
            if not relative:
                dir_data.append((file, checksum))
        result.append((dir, dir_data))
    return tuple(result)
