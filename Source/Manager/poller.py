import zmq
import socket
import select
import threading

import pickle
from time import time

import cProfile

from Common import recv_multipart, create_socket

class PollerBase:
    def __init__(self):
        def dummy(): pass
        self._stop_event = self.create_event(dummy)
        self._stopped = False

    def create_event(handler):
        raise NotImplementedError()

    def stop(self):
        self._stopped = True
        self._stop_event()

    def stopped(self):
        return self._stopped

class OSSelectPoller(PollerBase):
    class ZmqSocket:
        def __init__(self, socket, handler):
            self.socket = socket
            self.handler = handler

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
        def __init__(self, socket, handler):
            self.socket = socket
            self.handler = handler

        def registered(self):
            pass

        @classmethod
        def fileno_from_socket(cls, sock):
            return sock.fileno()

        def fileno(self):
            return self.fileno_from_socket(self.socket)

        def ready(self):
            self.handler(self.socket, self.socket.recv(256))

    class Event:
        def __init__(self, poller, handler):
            self.poller = poller
            with socket.socket() as listen_socket:
                listen_socket.bind(('', 0))
                listen_socket.listen(0)

                self.read = socket.socket()
                self.read.connect(('localhost', listen_socket.getsockname()[1]))
                self.poller.register(self.read, lambda ignore, ignore2 : handler())

                self.write, whatever = listen_socket.accept()

        def __call__(self):
            self.write.send(b'x')

        def close(self):
            self.poller.unregister(self.read)
            self.read.close()

    def __init__(self, zmq_ctx):
        PollerBase.__init__(self)
        self.pollin = set()
        self.pollout = set()
        self.sockets = {}
        self.events = set()

    @classmethod
    def __wrap_type(cls, sock):
        if isinstance(sock, zmq.Socket):
            return cls.ZmqSocket
        elif isinstance(sock, socket.socket):
            return cls.RawSocket

    def register(self, socket, handler):
        wrapped_socket = self.__wrap_type(socket)(socket, handler)
        fd = wrapped_socket.fileno()
        self.sockets[fd] = wrapped_socket
        self.pollin.add(fd)
        wrapped_socket.registered()

    def create_event(self, handler):
        event = self.Event(self, handler)
        self.events.add(event)
        return event

    def unregister(self, socket):
        fd = self.__wrap_type(socket).fileno_from_socket(socket)
        self.pollin.discard(fd)
        self.sockets.pop(fd)

    def run_for_a_while(self, timeout=None):
        pollin, pollout, pollerr = select.select(self.pollin, [], [], timeout)
        for fd in pollin:
            self.sockets[fd].ready()
        return bool(pollin)

    def run(self, observer):
        while True:
            if self.run_for_a_while(1):
                observer()
            if self.stopped():
                return

    def close(self):
        for event in self.events:
            event.close()
        self.sockets.clear()


class ZMQSelectPoller(PollerBase):
    class Event:
        def __init__(self, poller, handler):
            self.poller = poller
            self.address = 'inproc://preprocessing_{}'.format(id(self))
            self.event_socket = create_socket(self.poller.zmq_ctx, zmq.PULL)
            self.event_socket.bind(self.address)
            poller.register(self.event_socket, lambda socket, msgs : handler(), True)
            self.notify_sockets = {}

        def __call__(self):
            thread_id = threading.get_ident()
            notify_socket = self.notify_sockets.get(thread_id)
            if notify_socket is None:
                notify_socket = create_socket(self.poller.zmq_ctx, zmq.PUSH)
                notify_socket.connect(self.address)
                self.notify_sockets[thread_id] = notify_socket
            notify_socket.send(b'x')

        def close(self):
            for thread_id, notify_socket in self.notify_sockets.items():
                notify_socket.close()
            self.notify_sockets.clear()
            self.poller.unregister(self.event_socket)
            self.event_socket.close()

    def __init__(self, zmq_ctx):
        self.poller = zmq.Poller()
        self.zmq_ctx = zmq_ctx
        self.sockets = {}
        self.events = set()
        PollerBase.__init__(self)

    def create_event(self, handler):
        event = self.Event(self, handler)
        self.events.add(event)
        return event

    def register(self, socket, handler, process_all_msgs=False):
        self.sockets[socket] = handler, process_all_msgs
        self.poller.register(socket, zmq.POLLIN)

    def unregister(self, socket):
        del self.sockets[socket]
        self.poller.unregister(socket)

    def run_for_a_while(self, timeout=None):
        if timeout is not None:
            timeout *= 1000
        result = self.poller.poll(timeout)
        for socket, event in result:
            assert event == zmq.POLLIN
            handler, process_all_msgs = self.sockets[socket]
            if process_all_msgs:
                msgs = []
                try:
                    while True:
                        msgs.append(recv_multipart(socket, zmq.NOBLOCK))
                except zmq.ZMQError:
                    pass
                handler(socket, msgs)
            else:
                handler(socket, recv_multipart(socket, zmq.NOBLOCK))
        return bool(result)

    def run(self, observer):
        last_time = time()
        while True:
            if self.run_for_a_while(1):
                observer()
            if self.stopped():
                return

    def close(self):
        for event in self.events:
            event.close()
        for socket in self.sockets.keys():
            socket.close()
