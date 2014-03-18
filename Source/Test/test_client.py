import os
import subprocess
import asyncio
import sys
import pytest

sys.path.append('..')
from Common import MessageProtocol

class ProtocolTester(MessageProtocol):
    def __init__(self, loop):
        self.initial = True
        self.loop = loop
        super().__init__()

    def process_msg(self, msg):
        if self.initial:
            assert len(msg) > 5
            self.compiler_name = msg[0].decode()
            assert self.compiler_name == 'msvc'
            self.executable = msg[1].decode()
            assert os.path.exists(self.executable)
            assert os.path.isfile(self.executable)
            assert os.path.basename(self.executable) == 'cl.exe'
            self.sysincludes = msg[2].decode().rstrip(';').split(';')
            for path in self.sysincludes:
                assert os.path.exists(path)
                assert os.path.isdir(path)
            self.cwd = msg[3].decode()
            assert os.path.exists(self.cwd)
            assert os.path.isdir(self.cwd)
            self.command = [x.decode() for x in msg[4:]]
            self.send_request()
            self.initial = False
        else:
            self.process_response(msg)

    def send_request(self):
        raise NotImplementedError()

    def process_response(self, msg):
        raise NotImplementedError()

    def connection_lost(self, exc):
        self.loop.stop()

class RunLocallyTester(ProtocolTester):
    expected_exit_code = 0

    def send_request(self):
        self.send_msg([b'RUN_LOCALLY'])
        self.close()

class ExecuteAndExitTester(ProtocolTester):
    expected_exit_code = 2

    def send_request(self):
        self.send_msg([b'EXECUTE_AND_EXIT', b'/nologo'])
        self.close()

class ExecuteGetOutputTester(ProtocolTester):
    expected_exit_code = 6132

    def send_request(self):
        self.send_msg([b'EXECUTE_GET_OUTPUT', b'/nologo'])

    def process_response(self, msg):
        retcode, stdout, stderr = msg
        retcode = int(retcode.memory())
        assert retcode != 0
        assert not stdout.memory()
        assert b'missing source filename' in stderr.tobytes()
        self.send_msg([b'EXIT', b'6132', b'', b''])
        self.close()

class ExitTester(ProtocolTester):
    expected_exit_code = 666

    def send_request(self):
        self.send_msg([b'EXIT', b'666', b'', b''])
        self.close()

class LocateFiles(ProtocolTester):
    expected_exit_code = 3124

    files = [b'cl.exe', b'c1xx.dll']

    def send_request(self):
        self.send_msg([b'LOCATE_FILES'] + self.files)

    def process_response(self, msg):
        assert len(msg) == len(self.files)
        for file, full in zip(self.files, msg):
            assert os.path.basename(full.tobytes()) == file
            assert os.path.isfile(full.tobytes())
        self.send_msg([b'EXIT', b'3124', b'', b''])
        self.close()

@pytest.fixture(scope='module')
def bp_cl():
    return os.path.normpath(os.path.join(os.path.dirname(
        os.path.realpath(__file__)), '..', 'bp_cl.exe'))

@pytest.fixture(scope='module', params=['9.0', '10.0', '11.0', '12.0'])
def vcvarsall(request):
    import winreg
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

@pytest.fixture(scope='function')
def client_popen_args(tmpdir, vcvarsall, bp_cl):
    file = os.path.join(str(tmpdir), 'aaa.cpp')
    with open(file, 'wt'):
        pass
    return dict(args=[vcvarsall, '&&', bp_cl, '/c', file], cwd=str(tmpdir),
        stdout=sys.stdout, stderr=sys.stderr)

@pytest.mark.parametrize("protocol_tester", [RunLocallyTester,
    ExecuteGetOutputTester, ExecuteAndExitTester, ExitTester, LocateFiles])
def test_protocol(client_popen_args, protocol_tester):
    port = 'test_protocol_{}'.format(os.getpid())

    loop = asyncio.ProactorEventLoop()
    [server] = loop.run_until_complete(loop.start_serving_pipe(
        lambda : protocol_tester(loop), "\\\\.\\pipe\\BuildPal_{}".format(port)))

    env = os.environ
    env['BP_MGR_PORT'] = port
    with subprocess.Popen(env=env, **client_popen_args) as proc:
        loop.run_forever()
        @asyncio.coroutine
        def close_server():
            server.close()
        loop.run_until_complete(close_server())
        assert proc.wait() == protocol_tester.expected_exit_code

