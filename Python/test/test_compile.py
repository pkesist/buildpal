import buildpal_client

import os
import pytest
import sys
import tempfile
import shutil
import signal
import subprocess
import threading

from subprocess import list2cmdline, Popen

sys.path.append('..')

from time import sleep

MGR_PORT=33221
SRV_PORT=33222

class FileCreator:
    def __init__(self, tmpdir):
        self._tmpdir = tmpdir

    def create_file(self, filename, content=''):
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
    from buildpal.__main__ import main
    terminator = Terminator()
    def run_manager_thread():
        main(['mgr', 'client', '--ui=none', '--ini={}'.format(ini_file),
            '--port={}'.format(MGR_PORT), '--profile', 'test'], terminator)
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

def fallback(**kwargs):
    if 'reason' in kwargs:
        print(kwargs['reason'])
    return 666

@pytest.fixture(scope='function', params=(True, False))
def buildpal_compile(request, vcenv_and_cl, bp_cl, tmpdir):
    env, cl = vcenv_and_cl
    use_bp_cl = request.param
    if use_bp_cl:
        def func(args):
            env['BP_MANAGER_PORT'] = str(MGR_PORT)
            args[0] = bp_cl
            return subprocess.call(args, env=env, cwd=str(tmpdir))
        return func
    return lambda args : buildpal_client.compile("msvc", cl, env,
        list2cmdline(args), str(MGR_PORT), str(tmpdir), fallback)

@pytest.fixture(scope='module')
def run_server(request):
    from buildpal.__main__ import main
    terminator = Terminator()
    def run_server_thread():
        main(['srv', 'server', '--port={}'.format(SRV_PORT), '--silent'], terminator)
    server_thread = threading.Thread(target=run_server_thread)
    server_thread.start()
    def teardown():
        terminator.stop()
        server_thread.join()
    request.addfinalizer(teardown)
    return server_thread

def test_dummy(run_server, run_manager, buildpal_compile):
    assert buildpal_compile(['compiler', 'silly_option']) != 0

def test_relative(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('aaa/a1.cpp', '#include "../rel.hpp"\n')
    file_creator.create_file('rel.hpp', '\n')
    assert buildpal_compile(['compiler', '/c', file]) == 0

def test_system_headers(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('a2.cpp', '#include <vector>\n')
    assert buildpal_compile(['compiler', '/c', file]) == 0

def test_cplusplus(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('a3.cpp', '''\
#ifdef __cplusplus
#include "doesnotexist.hpp"
#endif
''')
    assert buildpal_compile(['compiler', '/c', file]) != 0

def test_link_and_run(file_creator, run_server, run_manager, buildpal_compile, vcenv_and_cl):
    file = file_creator.create_file('linkme.cpp', '''
#include <iostream>
int main()
{
    std::cout << "I'm a little teapot";
    return 0;
}
''')
    first_exe = file_creator.full_path('a_dist.exe')
    assert not os.path.exists(first_exe)
    assert buildpal_compile(['compiler', '/EHsc', file, '/link',
        "/SUBSYSTEM:CONSOLE", "/OUT:{}".format(first_exe)]) == 0
    assert os.path.exists(first_exe)

    second_exe = file_creator.full_path('a_local.exe')
    assert not os.path.exists(second_exe)
    env, cl = vcenv_and_cl
    with Popen([cl, '/EHsc', file, "/link", "/Ox", "/SUBSYSTEM:CONSOLE", "/OUT:{}".format(second_exe)],
            env=env) as proc:
        assert proc.wait(3) == 0
    assert os.path.exists(second_exe)
    with subprocess.Popen([first_exe], stdout=subprocess.PIPE) as proc:
        stdout, _ = proc.communicate()
        assert stdout == b"I'm a little teapot"
    assert os.stat(first_exe).st_size == os.stat(second_exe).st_size

def test_rel_include(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('imacppfile.cpp', '''
#include "xxx/bbb.h"
int main() {}
''')
    decoy = file_creator.create_file('imaheaderfile.hpp', '#error "I should not be included!"\n')
    realmccoy = file_creator.create_file('xxx/imaheaderfile.hpp', '\n')
    bbb = file_creator.create_file('xxx/bbb.h', '#include "imaheaderfile.hpp"')
    assert buildpal_compile(['compiler', '/c', file]) == 0

def test_error_on_include_out_of_include_path(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('test.cpp', '#include <asdf.h>')
    file_creator.create_file('inc/dodo.h')
    file_creator.create_file('inc/1/2/3/4/5/asdf.h', '#include "../../../../../dodo.h"')
    assert buildpal_compile(['compiler', '/c', '/Iinc/1/2/3/4/5', file]) == 0
