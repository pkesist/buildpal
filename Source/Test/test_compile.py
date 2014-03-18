import os
import pytest
import sys
import subprocess
import tempfile
import shutil
import signal

from time import sleep

MGR_PORT=33221
SRV_PORT=33222

def create_file(filename):
    return os.fdopen(os.open(filename, os.O_CREAT | os.O_WRONLY | os.O_NOINHERIT), 'w')

def terminate_proc(proc):
    proc.kill()
    proc.communicate()

@pytest.fixture(scope='module')
def run_manager(request):
    dir = tempfile.mkdtemp()
    ini_file = os.path.join(dir, 'test.ini')
    with create_file(ini_file) as ini:
        ini.write("""\
[test]
node[0]=localhost:{}:4

""".format(SRV_PORT))
    mgr_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'buildpal_manager.py'))
    proc = subprocess.Popen([sys.executable, mgr_script, '--ui=console',
        '--ini=test.ini', '--port={}'.format(MGR_PORT), 'test'], cwd=dir,
        stdout=subprocess.PIPE, stderr=sys.stderr, universal_newlines=True)
    sleep(1)
    def teardown():
        terminate_proc(proc)
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

@pytest.fixture(scope='module')
def run_server(request):
    dir = tempfile.mkdtemp()
    srv_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'buildpal_server.py'))
    proc = subprocess.Popen([sys.executable, srv_script,
        '--port={}'.format(SRV_PORT)], cwd=dir, stdout=subprocess.PIPE,
        stderr=sys.stderr, universal_newlines=True)
    def teardown():
        terminate_proc(proc)
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

def test_dummy(tmpdir, run_server, run_manager, vcvarsall, bp_cl):
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    with subprocess.Popen([vcvarsall, '&&', bp_cl, 'silly_option'], env=env,
        stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() != 0

def test_relative(tmpdir, run_server, run_manager, vcvarsall, bp_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'aaa', 'a1.cpp')
    os.makedirs(os.path.dirname(cpp_file))
    with create_file(cpp_file) as cpp:
        cpp.write('#include "../rel.hpp"\n')
    hpp_file = os.path.join(tmpdir, 'rel.hpp')
    with create_file(hpp_file) as hpp:
        hpp.write('\n')
    
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    with subprocess.Popen([vcvarsall, '&&', bp_cl, '/c', cpp_file],
        env=env, stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() == 0

def test_system_headers(tmpdir, run_server, run_manager, vcvarsall, bp_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'a2.cpp')
    with create_file(cpp_file) as cpp:
        cpp.write('#include <vector>\n')
    
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    with subprocess.Popen([vcvarsall, '&&', bp_cl, '/c', cpp_file],
        env=env, stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() == 0

def test_cplusplus(tmpdir, run_server, run_manager, vcvarsall, bp_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'a3.cpp')
    with create_file(cpp_file) as cpp:
        cpp.write('''\
#ifdef __cplusplus
#include "doesnotexist.hpp"
#endif
''')
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    with subprocess.Popen([vcvarsall, '&&', bp_cl, '/c', cpp_file],
        env=env, stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() != 0

def test_link(tmpdir, run_server, run_manager, vcvarsall, bp_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'linkme.cpp')
    with create_file(cpp_file) as cpp:
        cpp.write("int main() {}\n")
    env = os.environ
    env.update({'BP_MGR_PORT' : str(MGR_PORT), 'BP_DISABLE_FALLBACK': ''})
    with subprocess.Popen([vcvarsall, '&&', bp_cl, '/EHsc', cpp_file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:a_dist.exe"],
        env=env, cwd=tmpdir, stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() == 0
    assert os.path.exists(os.path.join(tmpdir, 'a_dist.exe'))

    with subprocess.Popen([vcvarsall, '&&', 'cl', '/EHsc', cpp_file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:a_local.exe"],
        env=env, cwd=tmpdir, stdout=sys.stdout, stderr=sys.stderr) as proc:
        assert proc.wait() == 0
    assert os.path.exists(os.path.join(tmpdir, 'a_local.exe'))

    assert os.stat(os.path.join(tmpdir, 'a_local.exe')).st_size == os.stat(os.path.join(tmpdir, 'a_dist.exe')).st_size

