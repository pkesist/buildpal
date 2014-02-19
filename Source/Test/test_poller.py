import pytest

import zmq
import sys
import threading

sys.path.append('..')

from Manager.poller import OSSelectPoller, ZMQSelectPoller
from time import sleep

def socket_pair(zmq_ctx, name):
    s1 = zmq_ctx.socket(zmq.DEALER)
    s2 = zmq_ctx.socket(zmq.DEALER)
    address = b'inproc://' + name
    s1.bind(address)
    s2.connect(address)
    return s1, s2

@pytest.mark.parametrize("poller_class", (OSSelectPoller, ZMQSelectPoller))
def test_recv(poller_class):
    readable = {}
    def __handle_socket(sock, msg):
        readable[sock] = msg

    zmq_ctx = zmq.Context()
    s11, s12 = socket_pair(zmq_ctx, b'asdf1')
    s21, s22 = socket_pair(zmq_ctx, b'asdf2')
    s31, s32 = socket_pair(zmq_ctx, b'asdf3')
    poller = poller_class(zmq_ctx)
    poller.register(s11, __handle_socket)
    poller.register(s21, __handle_socket)
    poller.register(s31, __handle_socket)
    s22.send(b'asdf')
    poller.run_for_a_while()
    assert readable.keys() == {s21}
    assert len(readable[s21]) == 1
    assert readable[s21][0] == b'asdf'
    readable.clear()
    s12.send(b'asdf')
    poller.run_for_a_while()
    assert readable.keys() == {s11}
    assert len(readable[s11]) == 1
    assert readable[s11][0] == b'asdf'

@pytest.mark.parametrize("poller_class", (OSSelectPoller, ZMQSelectPoller))
def test_event(poller_class):
    events_fired = set()

    def __handle_event(id):
        events_fired.add(id)

    def fire_event(event):
        event()

    zmq_ctx = zmq.Context()
    poller = poller_class(zmq_ctx)
    event1 = poller.create_event(lambda ev : __handle_event(1))
    event2 = poller.create_event(lambda ev : __handle_event(2))
    event3 = poller.create_event(lambda ev : __handle_event(3))

    thread = threading.Thread(target=fire_event, args=(event1,))
    thread.start()
    poller.run_for_a_while()
    thread.join()

    assert events_fired == {1}
    events_fired.clear()

    thread = threading.Thread(target=fire_event, args=(event2,))
    thread.start()
    poller.run_for_a_while()
    thread.join()

    assert events_fired == {2}
    events_fired.clear()

    thread = threading.Thread(target=fire_event, args=(event3,))
    thread.start()
    poller.run_for_a_while()
    thread.join()

    assert events_fired == {3}

