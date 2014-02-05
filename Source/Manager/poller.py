import zmq
import socket
import select

from Common import recv_multipart, create_socket

class PollerBase:
    def __init__(self):
        self._stopped = False

    def stop(self):
        self._stopped = True

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
        return self.Event(self, handler)

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
        self.sockets.clear()


class ZMQSelectPoller(PollerBase):
    class Event:
        def __init__(self, poller, handler):
            self.poller = poller
            self.address = 'inproc://preprocessing_{}'.format(id(self))
            self.event_socket = create_socket(self.poller.zmq_ctx, zmq.DEALER)
            self.event_socket.bind(self.address)
            poller.register(self.event_socket, lambda ignore, ignore2 : handler())

        def __call__(self):
            notify_socket = create_socket(self.poller.zmq_ctx, zmq.DEALER)
            notify_socket.connect(self.address)
            notify_socket.send(b'x')
            notify_socket.close()

        def close(self):
            self.poller.unregister(self.event_socket)
            self.event_socket.close()

    def __init__(self, zmq_ctx):
        PollerBase.__init__(self)
        self.poller = zmq.Poller()
        self.zmq_ctx = zmq_ctx
        self.sockets = {}

    def create_event(self, handler):
        return self.Event(self, handler)

    def register(self, socket, handler):
        self.sockets[socket] = handler
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
            handler = self.sockets[socket]
            handler(socket, recv_multipart(socket, zmq.NOBLOCK))
        return bool(result)

    def run(self, observer):
        while True:
            if self.run_for_a_while(1):
                observer()
            if self.stopped():
                return

    def close(self):
        for socket in self.sockets.keys():
            socket.close()
