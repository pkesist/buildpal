import zmq
import socket
import select

from Common import recv_multipart, create_socket

class PollerBase:
    def __init__(self):
        self._terminating = False

    def terminate(self):
        self._terminating = True

    def terminating(self):
        return self._terminating

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

    def run(self, printer):
        while True:
            printer()
            self.run_for_a_while(1)
            if self.terminating():
                return

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
            notify_socket.disconnect(self.address)

        def close(self):
            self.poller.unregister(self.event_socket)
            self.event_socket.unbind(self.address)

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

    def run(self, printer):
        while True:
            printer()
            self.run_for_a_while(1)
            if self.terminating():
                return

has_asyncio = True
try:
    import asyncio
except ImportError:
    has_asyncio = False

if has_asyncio:
    class AsyncIOPoller:
        class Event:
            def __init__(self, proactor, event):
                self.proactor = proactor
                self.event = event

            def __call__(self):
                self.proactor.call_soon_threadsafe(lambda : self.event.set())

            def clear(self):
                self.event.clear()

            def close():
                pass

        class SocketWrapper:
            def __init__(self, fileno):
                self._fileno = fileno

            def fileno(self):
                return self._fileno

        def __init__(self, zmq_ctx):
            self.proactor = asyncio.ProactorEventLoop()
            self.registered_sockets = set()

        @asyncio.coroutine
        def handle_socket(self, zmq_socket, handler, sock=None, first=True):
            assert zmq_socket in self.registered_sockets
            if sock is None:
                fd = zmq_socket.getsockopt(zmq.FD)
                sock = SocketWrapper(fd)
            if first:
                self.handle_tasks(zmq_socket, handler)
            yield from self.proactor.sock_recv(sock, 0)
            self.handle_tasks(zmq_socket, handler)
            asyncio.async(self.handle_socket(zmq_socket, handler, sock=sock, first=False), loop=self.proactor)

        def handle_tasks(self, socket, handler):
            assert socket in self.registered_sockets
            while socket.getsockopt(zmq.EVENTS) & zmq.POLLIN:
                handler(socket, recv_multipart(socket, zmq.NOBLOCK))

        @asyncio.coroutine
        def handle_event(self, event, handler):
            yield from event.wait()
            event.clear()
            handler()
            asyncio.async(self.handle_event(event, handler), loop=self.proactor)

        @asyncio.coroutine
        def print(self, printer):
            printer()
            yield from asyncio.sleep(2, loop=self.proactor)
            asyncio.async(self.print(printer), loop=self.proactor)

        def create_event(self, handler):
            event = asyncio.Event(loop=self.proactor)
            asyncio.async(self.handle_event(event, handler), loop=self.proactor)
            return self.Event(self.proactor, event)

        def register(self, socket, handler):
            assert socket not in self.registered_sockets
            self.registered_sockets.add(socket)
            asyncio.async(self.handle_socket(socket, handler), loop=self.proactor)

        def unregister(self, socket):
            self.registered_sockets.remove(socket)

        def run(self, printer):
            asyncio.async(self.print(printer), loop=self.proactor)
            self.proactor.run_forever()
