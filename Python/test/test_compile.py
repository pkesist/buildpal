import buildpal_client

import os
import pytest
import sys
import tempfile
import shutil
import signal
import subprocess
import threading
from conftest import Terminator

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
        main(['buildpal', 'manager', '--ui=none', '--ini={}'.format(ini_file),
            '--port={}'.format(MGR_PORT), '--profile', 'test'], terminator)
    manager_thread = threading.Thread(target=run_manager_thread)
    manager_thread.start()
    # Give it some time to set up.
    sleep(4)
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

class InternalCompile: pass
class CompilerSubstitute: pass
class CreateProcessHook: pass
class CompilerSubstituteHook: pass

@pytest.fixture(scope='function', params=(
    InternalCompile,
    CompilerSubstitute,
    CreateProcessHook,
    CompilerSubstituteHook
))
def buildpal_compile(request, vcenv_and_cl, bp_cl, tmpdir):
    vcenv, cl = vcenv_and_cl
    if request.param == InternalCompile:
        def func(args, env={}):
            env.update(vcenv)
            return buildpal_client.compile("msvc", cl, env,
            list2cmdline(args), str(MGR_PORT), str(tmpdir), fallback)
    elif request.param == CompilerSubstitute:
        def func(args, env={}):
            env['BP_MANAGER_PORT'] = str(MGR_PORT)
            args[0] = bp_cl
            env.update(vcenv)
            return subprocess.call(args, env=env, cwd=str(tmpdir))
    else:
        assert request.param in (CreateProcessHook, CompilerSubstituteHook)
        from buildpal.__main__ import main
        call = [sys.executable, '-m', 'buildpal', 'client', '--connect', str(MGR_PORT)]
        if request.param == CreateProcessHook:
            call.append('--no-cp')
        call.append('--run')
        def func(args, env={}):
            args[0] = 'cl'
            env.update(vcenv)
            return subprocess.call(call + args, env=env, cwd=str(tmpdir), shell=False)
    return func

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

def test_link_and_run(file_creator, tmpdir, run_server, run_manager, buildpal_compile, vcenv_and_cl):
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
    params = ['/EHsc', file, '/Ox', '/link', '/SUBSYSTEM:CONSOLE']
    assert buildpal_compile(['compiler'] + params + ["/OUT:{}".format(first_exe)]) == 0
    assert os.path.exists(first_exe)

    second_exe = file_creator.full_path('a_local.exe')
    assert not os.path.exists(second_exe)
    env, cl = vcenv_and_cl
    with Popen([cl] + params + ["/OUT:{}".format(second_exe)],
            env=env, cwd=str(tmpdir)) as proc:
        assert proc.wait(3) == 0
    assert os.path.exists(second_exe)
    with subprocess.Popen([first_exe], stdout=subprocess.PIPE, cwd=str(tmpdir)) as proc:
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

def test_lib_input(file_creator, run_server, run_manager, buildpal_compile, vcenv_and_cl):
    file = file_creator.create_file('asdf.cpp', '''\
#include <windows.h>

int main() { RegCloseKey( (HKEY)0 ); }
''')
    args = ['cl', '/EHsc', file, 'advapi32.lib', '/link', '/SUBSYSTEM:CONSOLE']
    assert buildpal_compile(args) == 0

def test_exe_name(file_creator, run_server, run_manager, buildpal_compile, vcenv_and_cl):
    file = file_creator.create_file('asdf.cpp', '''\
int main() {}
''')
    args = ['cl', '/EHsc', file, '/Fexxee.exe', '/link', '/SUBSYSTEM:CONSOLE']
    assert buildpal_compile(args) == 0
    exe_path = file_creator.full_path('xxee.exe')
    assert os.path.exists(exe_path)

def test_pch(tmpdir, file_creator, run_server, run_manager, buildpal_compile, vcenv_and_cl):
    pch_file = file_creator.create_file('pch.hpp', '')
    cpp_file = file_creator.create_file('cpp.cpp', '#include "pch.hpp"\n')
    test_file = file_creator.create_file('test.cpp', '#include "pch.hpp"\n')
    assert buildpal_compile(['cl', '/c', '/EHsc', '/Zi', '/Ycpch.hpp', cpp_file]) == 0
    assert buildpal_compile(['cl', '/EHsc', '/c', '/Zi', '/Yupch.hpp', '/Fppch.pch', test_file]) == 0
    vcenv, cl = vcenv_and_cl

def test_env_cl_opts(tmpdir, file_creator, run_server, run_manager, buildpal_compile):
    cpp_file = file_creator.create_file('cpp.cpp', '''
#ifndef DEFINED_BY_ENV
#error "DEFINED_BY_ENV not defined"
#endif
''')
    assert buildpal_compile(['compiler', '/c', cpp_file]) != 0
    assert buildpal_compile(['compiler', '/c', cpp_file], env={'CL': '/DDEFINED_BY_ENV'}) == 0


def test_error_on_include_out_of_include_path(file_creator, run_server, run_manager, buildpal_compile):
    file = file_creator.create_file('test.cpp', '#include <asdf.h>')
    file_creator.create_file('inc/dodo.h')
    file_creator.create_file('inc/1/2/3/4/5/asdf.h', '#include "../../../../../dodo.h"')
    assert buildpal_compile(['compiler', '/c', '/Iinc/1/2/3/4/5', file]) == 0

def test_include_order(file_creator, run_server, run_manager, buildpal_compile):
    rightfile = file_creator.create_file('right.h', '')
    wrongfile = file_creator.create_file('wrong.h', '#error "You should not have included me!!!"')
    first  = file_creator.create_file('first/include.h' , '#include "../right.h"\n')
    second = file_creator.create_file('second/include.h', '#include "../wrong.h"\n')
    third  = file_creator.create_file('third/include.h' , '#include "../wrong.h"\n')
    fourth = file_creator.create_file('fourth/include.h', '#include "../wrong.h"\n')
    file = file_creator.create_file('test.cpp', '#include "include.h"\n')
    assert buildpal_compile(['compiler', '/c', '/Ifirst', '/Isecond', '/Ithird', '/Ifourth', file]) == 0

@pytest.mark.parametrize('src_file_option', ('', '/Tp', '/Tc'))
def test_src_file_option(file_creator, run_server, run_manager, buildpal_compile, src_file_option):
    cpp_file = file_creator.create_file('test.cpp', '')
    assert buildpal_compile(['compiler', '/c', '{}{}'.format(src_file_option, cpp_file), '/Foburek.obj']) == 0
