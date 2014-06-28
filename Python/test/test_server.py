import threading
import pytest
from buildpal.common import msg_to_bytes

from conftest import Terminator

SRV_PORT = 13132

@pytest.fixture(scope='module')
def run_server(request):
    from buildpal.__main__ import main
    terminator = Terminator()
    def run_server_thread():
        main(['buildpal', 'server', '--port={}'.format(SRV_PORT), '--silent'], terminator)
    server_thread = threading.Thread(target=run_server_thread)
    server_thread.start()
    def teardown():
        terminator.stop()
        server_thread.join()
    request.addfinalizer(teardown)
    return server_thread

def test_remote_reset(run_server):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', SRV_PORT))
    for buffer in msg_to_bytes([b'RESET']):
        sock.send(buffer)
    assert run_server.is_alive()
    run_server.join(1)
    assert run_server.is_alive()

def test_remote_shutdown(run_server):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(('127.0.0.1', SRV_PORT))
    for buffer in msg_to_bytes([b'SHUTDOWN']):
        sock.send(buffer)
    assert run_server.is_alive()
    run_server.join(1)
    assert not run_server.is_alive()
