import os
import pytest
import winreg
import sys
import subprocess

@pytest.fixture(scope='module')
def bp_cl():
    return os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', '..', 'bp_cl.exe'))

def vcvarsall(version):
    dir = None
    try:
        win32subkey = "WOW6432Node\\" if sys.maxsize > 2**32 else ""
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\{}Microsoft\VisualStudio\{}\Setup\VC'.
            format(win32subkey, version)) as key:
            dir = winreg.QueryValueEx(key, 'ProductDir')[0]
    except:
        pass
    if not dir:
        pytest.skip("Visual Studio {} not found.".format(version))
    return os.path.join(dir, 'vcvarsall.bat')

@pytest.fixture(scope='module', params=['9.0', '10.0', '11.0', '12.0'])
def vcenv(request):
    vcvars = vcvarsall(request.param)
    with subprocess.Popen('{} >NUL && set'.format(vcvars),
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
    return res



