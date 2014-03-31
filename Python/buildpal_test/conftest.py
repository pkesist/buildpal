import os
import pytest
import winreg

@pytest.fixture(scope='module')
def bp_cl():
    return os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'bp_cl.exe'))

@pytest.fixture(scope='module', params=['9.0', '10.0', '11.0', '12.0'])
def vcvarsall(request):
    version = request.param
    dir = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\VisualStudio\{}\Setup\VC'.
            format(version)) as key:
            dir = winreg.QueryValueEx(key, 'ProductDir')[0]
    except:
        pass
    if not dir:
        pytest.skip("Visual Studio {} not found.".format(version))
    return os.path.join(dir, 'vcvarsall.bat')
