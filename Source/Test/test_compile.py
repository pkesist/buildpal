import os
import pytest
import sys
import subprocess
import tempfile
import shutil
import signal

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
    ini_file = os.path.join(dir, 'distribute_manager.ini')
    with create_file(ini_file) as ini:
        ini.write("""\
[Manager]
port={}

[Default Profile]
node[0]=localhost:{}:4

""".format(MGR_PORT, SRV_PORT))
    mgr_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'distribute_manager.py'))
    proc = subprocess.Popen([sys.executable, mgr_script], cwd=dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def teardown():
        terminate_proc(proc)
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

@pytest.fixture(scope='module')
def run_server(request):
    dir = tempfile.mkdtemp()
    srv_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'distribute_server.py'))
    proc = subprocess.Popen([sys.executable, srv_script,
            '--port={}'.format(SRV_PORT)], cwd=dir, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    def teardown():
        terminate_proc(proc)
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

@pytest.fixture(scope='module')
def db_cl():
    return os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'db_cl.exe'))

@pytest.fixture(scope='module')
def vcvarsall():
    import winreg
    versions = ['9.0', '10.0', '11.0']
    dir = None
    for version in versions:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\VisualStudio\{}\Setup\VC'.
                format(version)) as key:
                dir = winreg.QueryValueEx(key, 'ProductDir')[0]
                break
        except:
            pass
    if not dir:
        raise Exception("Failed to locate Visual Studio on system")
    return os.path.join(dir, 'vcvarsall.bat')


def test_dummy(tmpdir, vcvarsall, db_cl):
    with subprocess.Popen([vcvarsall, '&&', db_cl, 'silly_option'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode != 0

def test_relative(tmpdir, run_server, run_manager, vcvarsall, db_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'aaa', 'a.cpp')
    os.makedirs(os.path.dirname(cpp_file))
    with create_file(cpp_file) as cpp:
        cpp.write('#include "../rel.hpp"\n')
    hpp_file = os.path.join(tmpdir, 'rel.hpp')
    with create_file(hpp_file) as hpp:
        hpp.write('\n')
    
    env = os.environ
    env.update({'DB_MGR_PORT' : str(MGR_PORT)})
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/c', cpp_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0

def test_cplusplus(tmpdir, run_server, run_manager, vcvarsall, db_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'a.cpp')
    with create_file(cpp_file) as cpp:
        cpp.write('''\
#ifdef __cplusplus
#include "doesnotexist.hpp"
#endif
''')
    env = os.environ
    env.update({'DB_MGR_PORT' : str(MGR_PORT)})
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/c', cpp_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode != 0


def test_link(tmpdir, run_server, run_manager, vcvarsall, db_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'linkme.cpp')
    with create_file(cpp_file) as cpp:
        cpp.write("int main() {}\n")
    env = os.environ
    env.update({'DB_MGR_PORT' : str(MGR_PORT)})
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/EHsc', cpp_file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:a_dist.exe"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=tmpdir) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0
    assert os.path.exists(os.path.join(tmpdir, 'a_dist.exe'))

    with subprocess.Popen([vcvarsall, '&&', 'cl', '/EHsc', cpp_file, "/link", "/SUBSYSTEM:CONSOLE", "/OUT:a_local.exe"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=tmpdir) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0
    assert os.path.exists(os.path.join(tmpdir, 'a_local.exe'))

    assert os.stat(os.path.join(tmpdir, 'a_local.exe')).st_size == os.stat(os.path.join(tmpdir, 'a_dist.exe')).st_size

