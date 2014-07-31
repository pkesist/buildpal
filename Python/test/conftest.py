import os
import pytest
import winreg
import sys
import subprocess

@pytest.fixture(scope='module')
def bp_cl():
    from buildpal.client.__main__ import find_bp_cl
    try:
        return find_bp_cl()
    except EnvironmentError:
        pytest.skip("Could not find 'bp_cl.exe'")

def vcvarsall(version):
    dir = None
    for kind in ('VisualStudio', 'VCExpress'):
        try:
            win32subkey = "WOW6432Node\\" if sys.maxsize > 2**32 else ""
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\{}Microsoft\{}\{}\Setup\VC'.
                format(win32subkey, kind, version)) as key:
                dir = winreg.QueryValueEx(key, 'ProductDir')[0]
                return os.path.join(dir, 'vcvarsall.bat')
        except FileNotFoundError:
            pass
    pytest.skip("Visual Studio {} not found.".format(version))


@pytest.fixture(scope='module', params=(
    ('9.0' , 'x86'), ('9.0' , 'amd64'), ('9.0' , 'x86_amd64'), ('9.0', 'x86_ia64'),
    ('10.0', 'x86'), ('10.0', 'amd64'), ('10.0', 'x86_amd64'),
    ('11.0', 'x86'), ('11.0', 'amd64'), ('11.0', 'x86_amd64'),
    ('12.0', 'x86'), ('12.0', 'amd64'), ('12.0', 'x86_amd64'),
    )
)
def vcenv_and_cl(request):
    vcvars = vcvarsall(request.param[0])
    with subprocess.Popen('"{}" {}>NUL && set'.format(vcvars, request.param[1]),
            stdout=subprocess.PIPE) as proc:
        stdout, _ = proc.communicate()
    vars = stdout.decode()
    vars = vars.split('\r\n')
    assert vars[-1] == ''
    del vars[-1]
    res = {}
    for var in vars:
        eq_pos = var.index('=')
        res[var[:eq_pos].upper()] = var[eq_pos + 1:]

    cl = None
    for dir in res['PATH'].split(os.path.pathsep):
        tmp = os.path.join(dir, 'cl.exe')
        if os.path.exists(tmp):
            cl = tmp
            break
    if not cl:
        pytest.skip("Skipped test due to missing cl.exe.")
    return res, cl

class Terminator:
    def __init__(self):
        self.stop_func = None
        self.should_stop = False

    def initialize(self, stop_func):
        self.stop_func = stop_func
        if self.should_stop:
            self.stop()

    def stop(self):
        if self.stop_func:
            self.stop_func()
        else:
            self.should_stop = True


