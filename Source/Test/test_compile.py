import os
import pytest
import sys
import subprocess
import tempfile
import shutil
import signal

MGR_PORT=33221
SRV_PORT=33222

@pytest.fixture(scope='module')
def run_manager(request):
    dir = tempfile.mkdtemp()
    ini_file = os.path.join(dir, 'distribute_manager.ini')
    with open(ini_file, 'w') as ini:
        ini.write("""\
[Manager]
port={}

[Default Profile]
node[0]=localhost:{}:4

""".format(MGR_PORT, SRV_PORT))
    mgr_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'distribute_manager.py'))
    proc = subprocess.Popen([sys.executable, mgr_script], cwd=dir, shell=True)
    def teardown():
        proc.terminate()
        proc.wait()
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

@pytest.fixture(scope='module')
def run_server(request):
    dir = tempfile.mkdtemp()
    ini_file = os.path.join(dir, 'distribute_server.ini')
    with open(ini_file, 'w') as ini:
        ini.write("""\
[Server]
port={}
""".format(SRV_PORT))
    srv_script = os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'distribute_server.py'))
    proc = subprocess.Popen([sys.executable, srv_script], cwd=dir, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def teardown():
        proc.terminate()
        proc.wait()
        shutil.rmtree(dir)
    request.addfinalizer(teardown)
    return proc

@pytest.fixture(scope='module')
def db_cl():
    return os.path.join('..', 'db_cl.exe')

@pytest.fixture(scope='module')
def vcvarsall():
    import winreg
    versions = ['9.0', '10.0', '11.0']
    dir = None
    for version in versions:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\VisualStudio\{}\Setup\VC'.
                format('9.0')) as key:
                dir = winreg.QueryValueEx(key, 'ProductDir')[0]
                break
        except:
            pass
    if not dir:
        raise Exception("Failed to locate Visual Studio on system")
    return os.path.join(dir, 'vcvarsall.bat')


#def test_dummy(tmpdir, vcvarsall, db_cl):
#    with subprocess.Popen([vcvarsall, '&&', db_cl, 'silly_option'],
#        stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
#        stdout, stderr = proc.communicate()
#        assert proc.returncode != 0

def test_relative(tmpdir, run_server, run_manager, vcvarsall, db_cl):
    tmpdir = str(tmpdir)
    cpp_file = os.path.join(tmpdir, 'aaa', 'a.cpp')
    os.makedirs(os.path.dirname(cpp_file))
    with open(cpp_file, 'w') as cpp:
        cpp.write('#include "../rel.hpp"\n')
    hpp_file = os.path.join(tmpdir, 'rel.hpp')
    with open(hpp_file, 'w') as hpp:
        hpp.write('\n')
    
    env = os.environ
    env.update({'DB_MGR_PORT' : str(MGR_PORT)})
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/c', cpp_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0

def test_compile(tmpdir, run_server, run_manager, vcvarsall, db_cl):
    cpp_file = os.path.join(str(tmpdir), 'a.cpp')
    with open(cpp_file, 'w') as cpp:
        cpp.write("int main() {}\n")
    env = os.environ
    env.update({'DB_MGR_PORT' : str(MGR_PORT)})
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/EHsc', cpp_file, "/link", "/SUBSYSTEM:CONSOLE"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0

    



