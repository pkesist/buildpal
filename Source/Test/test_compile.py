import os
import pytest
import subprocess

@pytest.fixture(scope='module')
def db_cl():
    return os.path.join('..', 'db_cl.exe')

@pytest.fixture(scope='module')
def vcvarsall():
    import winreg
    versions = ['11.0', '10.0', '9.0']
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


def test_compile(tmpdir, vcvarsall, db_cl):
    cpp_file = os.path.join(str(tmpdir), 'a.cpp')
    with open(cpp_file, 'w') as cpp:
        cpp.write("int main() {}\n")
    with subprocess.Popen([vcvarsall, '&&', db_cl, '/EHsc', cpp_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        stdout, stderr = proc.communicate()
        assert proc.returncode == 0

    



