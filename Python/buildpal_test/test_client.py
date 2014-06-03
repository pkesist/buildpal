from buildpal_client import compile as buildpal_compile

import os
import subprocess
import asyncio
import sys
import struct
import threading
import pytest

from buildpal_common import MessageProtocol

class ProtocolTester(MessageProtocol):
    @classmethod
    def check_exit_code(cls, code):
        if hasattr(cls, 'expected_exit_code'):
            assert code == cls.expected_exit_code

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

class ExecuteAndExitTester(ProtocolTester):
    @classmethod
    def check_exit_code(cls, code):
        assert code != 0

    def send_request(self):
        self.send_msg([b'EXECUTE_AND_EXIT', b'/nologo'])

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
        self.send_msg([b'EXIT', struct.pack('!I', self.expected_exit_code & 0xFFFFFFFF), b'',
            b''])

class ExitTester(ProtocolTester):
    expected_exit_code = 666

    def send_request(self):
        self.send_msg([b'EXIT', struct.pack('!I', self.expected_exit_code & 0xFFFFFFFF), b'',
            b''])

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
        self.send_msg([b'EXIT', struct.pack('!I', self.expected_exit_code & 0xFFFFFFFF), b'',
            b''])

@pytest.fixture(scope='function')
def buildpal_compile_args(tmpdir, vcenv_and_cl):
    port = 'test_protocol_{}'.format(os.getpid())
    file = os.path.join(str(tmpdir), 'aaa.cpp')
    with open(file, 'wt'):
        pass
    args = ['compile', '/c', file]

    env, cl = vcenv_and_cl
    return ("msvc", cl, env, subprocess.list2cmdline(args), port)

@pytest.mark.parametrize("protocol_tester", [RunLocallyTester,
    ExecuteGetOutputTester, ExecuteAndExitTester, ExitTester, LocateFiles])
def test_protocol(buildpal_compile_args, protocol_tester):
    loop = asyncio.ProactorEventLoop()
    [server] = loop.run_until_complete(loop.start_serving_pipe(
        lambda : protocol_tester(loop), "\\\\.\\pipe\\BuildPal_{}".format(buildpal_compile_args[-1])))

    class ExitCode:
        pass

    def run_thread():
        ExitCode.exit_code = buildpal_compile(*buildpal_compile_args)

    thread = threading.Thread(target=run_thread)
    thread.start()
    loop.run_forever()
    thread.join()
    @asyncio.coroutine
    def close_server():
        server.close()
    loop.run_until_complete(close_server())
    assert ExitCode.exit_code != None
    protocol_tester.check_exit_code(ExitCode.exit_code)

