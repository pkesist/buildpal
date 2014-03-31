import os
import pytest
import sys
import tempfile
import shutil
import signal
import threading

from subprocess import Popen

sys.path.append('..')

from time import sleep

MGR_PORT=33221
SRV_PORT=33222

class FileCreator:
    def __init__(self, tmpdir):
        self._tmpdir = tmpdir

    def create_file(self, filename, content):
        filename = os.path.join(self._tmpdir, filename)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'wt') as file:
            file.write(content)
        return filename

    def full_path(self, filename):
        return os.path.join(self._tmpdir, filename)

@pytest.fixture(scope='function')
def file_creator(tmpdir):
    return FileCreator(str(tmpdir))

def terminate_proc(proc):
    proc.kill()
    proc.communicate()

class Terminator:
    def __init__(self):
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def should_stop(self):
        return self._should_stop

@pytest.fixture(scope='module')
def run_manager(request):
    dir = tempfile.mkdtemp()
    ini_file = os.path.join(dir, 'test.ini')
    with open(ini_file, 'wt') as ini:
        ini.write("""\
[test]
node[0]=localhost:{}:4

""".format(SRV_PORT))
    import buildpal_manager
    terminator = Terminator()
    def run_manager_thread():
        buildpal_manager.main(['--ui=console', '--ini={}'.format(ini_file), '--port={}'.format(MGR_PORT), 'test'], terminator)
    manager_thread = threading.Thread(target=run_manager_thread)
    manager_thread.start()
    # Give it some time to set up.
    sleep(0.5)
    def teardown():
        shutil.rmtree(dir)
        terminator.stop()
        manager_thread.join()
    request.addfinalizer(teardown)
    return manager_thread

@pytest.fixture(scope='function')
def client_popen_args(tmpdir):
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    return dict(env=env, stderr=sys.stderr, stdout=sys.stdout, cwd=str(tmpdir))

@pytest.fixture(scope='module')
def run_server(request):
    import buildpal_server
    terminator = Terminator()
    def run_server_thread():
        buildpal_server.main(['--port={}'.format(SRV_PORT)], terminator)
    server_thread = threading.Thread(target=run_server_thread)
    server_thread.start()
    def teardown():
        terminator.stop()
        server_thread.join()
    request.addfinalizer(teardown)
    return server_thread

def test_dummy(run_server, run_manager, vcvarsall, bp_cl, client_popen_args):
    with Popen([vcvarsall, '&&', bp_cl, 'silly_option'], 
        **client_popen_args) as proc:
        assert proc.wait() != 0

def test_relative(file_creator, run_server, run_manager, vcvarsall, bp_cl, client_popen_args):
    file = file_creator.create_file('aaa/a1.cpp', '#include "../rel.hpp"\n')
    file_creator.create_file('rel.hpp', '\n')
    
    with Popen([vcvarsall, '&&', bp_cl, '/c', file],
        **client_popen_args) as proc:
        assert proc.wait() == 0

def test_system_headers(file_creator, run_server, run_manager, vcvarsall, bp_cl, client_popen_args):
    file = file_creator.create_file('a2.cpp', '#include <vector>\n')
    with Popen([vcvarsall, '&&', bp_cl, '/c', file],
        **client_popen_args) as proc:
        assert proc.wait() == 0

def test_cplusplus(file_creator, run_server, run_manager, vcvarsall, bp_cl, client_popen_args):
    file = file_creator.create_file('a3.cpp', '''\
#ifdef __cplusplus
#include "doesnotexist.hpp"
#endif
''')

    with Popen([vcvarsall, '&&', bp_cl, '/c', file],
        **client_popen_args) as proc:
        assert proc.wait() != 0

def test_link(file_creator, run_server, run_manager, vcvarsall, bp_cl, client_popen_args):
    file = file_creator.create_file('linkme.cpp', "int main() {}\n")
    first_exe = file_creator.full_path('a_dist.exe')
    assert not os.path.exists(first_exe)
    with Popen([vcvarsall, '&&', bp_cl, '/EHsc', file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:{}".format(first_exe)],
        **client_popen_args) as proc:
        assert proc.wait() == 0
    assert os.path.exists(first_exe)

    second_exe = file_creator.full_path('a_local.exe')
    assert not os.path.exists(second_exe)
    with Popen([vcvarsall, '&&', 'cl', '/EHsc', file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:{}".format(second_exe)],
        **client_popen_args) as proc:
        assert proc.wait() == 0
    assert os.path.exists(second_exe)

    assert os.stat(first_exe).st_size == os.stat(second_exe).st_size

