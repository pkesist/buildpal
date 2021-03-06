from buildpal.common import SimpleTimer, Timer, MessageProtocol, compress_file

import asyncio

from io import BytesIO, StringIO
from multiprocessing import cpu_count
from struct import pack
from time import time
from concurrent.futures import ThreadPoolExecutor

from .header_repository import HeaderRepository
from .pch_repository import PCHRepository
from .compiler_repository import CompilerRepository

from buildpal.common.beacon import Beacon

import map_files

import logging
import os
import pickle
import sched
import shutil
import socket
import struct
import subprocess
import sys
import traceback
import tempfile
import zipfile
import zlib

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

class OverrideCreateProcess:
    def __init__(self, file_maps):
        if file_maps:
            self.file_map_composition = map_files.FileMapComposition(*file_maps)
        else:
            self.file_map_composition = None
        self.save = None

    def __enter__(self):
        if self.file_map_composition:
            self.save = subprocess._winapi.CreateProcess
            subprocess._winapi.CreateProcess = \
                self.file_map_composition.create_process

    def __exit__(self, exc_type, exc_value, traceback):
        if self.save:
            subprocess._winapi.CreateProcess = self.save
            self.save = None

class CompileSession(Timer):
    class SessionState:
        can_be_cancelled = False

        @classmethod
        def cancel(cls, session): pass

        @classmethod
        def enter_state(cls, session): pass

        @classmethod
        def exit_state(cls, session): pass

    class StateGetTask(SessionState):
        @classmethod
        def process_msg(cls, session, msg):
            assert len(msg) == 2
            assert msg[0] == b'SERVER_TASK'
            session.task = pickle.loads(msg[1].memory())
            session.note_time('received task', 'waiting for task')
            # Determine headers which are missing
            missing_files_timer = SimpleTimer()
            missing_files = \
                session.runner.header_repository().missing_files(
                session.task.fqdn, id(session), session.task.filelist)
            # Determine if we have this compiler
            session.compiler_required = session.runner.compiler_repository(
                ).compiler_required(session.compiler_id())

            # Determine whether we need pch PCH file.
            if session.task.pch_file is None:
                session.pch_required = False
            else:
                session.pch_file, session.pch_required = \
                    session.runner.pch_repository().register_file(
                        session.task.pch_file)
            session.sender.send_msg([session.local_id, b'MISSING_FILES',
                pickle.dumps((missing_files, session.compiler_required,
                session.pch_required))])
            session.note_time('determined missing files', 'determine missing files')
            session.change_state(CompileSession.StateDownloadMissingHeaders)

    class StateDownloadMissingHeaders(SessionState):
        @classmethod
        def process_msg(cls, session, msg):
            assert msg[0] == b'TASK_FILES'
            msg.pop(0)
            assert len(msg) % 3 == 0
            parts = len(msg) // 3
            new_files = {}
            for part in range(parts):
                dir, file, content = msg[3 * part:3 * part + 3]
                new_files[(dir.decode(), file.decode())] = content.tobytes()
            session.note_time('received missing headers', 'downloading headers')
            session.waiting_for_manager_data = SimpleTimer()
            session.include_dirs_future = session.prepare_include_dirs(
                session.runner.misc_thread_pool(), new_files)
            if session.compiler_required:
                session.change_state(CompileSession.StateDownloadingCompiler)
                session.compiler_data = BytesIO()
            elif session.pch_required:
                session.change_state(session.StateDownloadingPCH)
            else:
                session.compile()

    class StateDownloadingCompiler(SessionState):
        @classmethod
        def process_msg(cls, session, msg):
            more, data = msg
            session.compiler_data.write(data.memory())
            if more == b'\x00':
                session.note_time('received compiler', 'downloading compiler')
                session.compiler_data.seek(0)
                dir = session.runner.compiler_repository().compiler_dir(
                    session.compiler_id())
                os.makedirs(dir, exist_ok=True)
                with zipfile.ZipFile(session.compiler_data) as zip:
                    zip.extractall(path=dir)
                del session.compiler_data
                session.runner.compiler_repository().set_compiler_ready(
                    session.compiler_id())
                if session.pch_required:
                    session.change_state(session.StateDownloadingPCH)
                else:
                    session.compile()

    class StateDownloadingPCH(SessionState):
        @classmethod
        def enter_state(cls, session):
            session.pch_timer = SimpleTimer()
            session.pch_desc = BytesIO()
            session.pch_decompressor = zlib.decompressobj()

        @classmethod
        def process_msg(cls, session, msg):
            more, data = msg
            session.pch_desc.write(session.pch_decompressor.decompress(data.memory()))

            def buffer_to_file(buffer, filename):
                buf = BytesIO(buffer)
                with open(filename, 'wb') as file:
                    for data in iter(lambda : buf.read(256 * 1024), b''):
                        file.write(data)

            def pch_completed(future):
                session.note_time('received pch', 'downloading pch')
                session.runner.pch_repository().file_completed(session.task.pch_file)
                session.compile()

            if more == b'\x00':
                session.pch_desc.write(session.pch_decompressor.flush())
                session.runner.async_run(buffer_to_file,
                    session.pch_desc.getbuffer(), session.pch_file
                    ).add_done_callback(pch_completed)

        @classmethod
        def exit_state(cls, session):
            session.pch_desc.close()
            del session.pch_desc
            del session.pch_decompressor

    class StateRunningCompiler(SessionState):
        can_be_cancelled = True

        @classmethod
        def cancel(cls, session):
            if session.process is not None:
                try:
                    session.process.terminate()
                except ProcessLookupError:
                    pass

    class StateWaitForConfirmation(SessionState):
        can_be_cancelled = True

        @classmethod
        def process_msg(cls, session, msg):
            tag, verdict = msg
            assert tag == b'SEND_CONFIRMATION'
            if verdict == b'\x01':
                session.change_state(CompileSession.StateUploadingFile)
                session.send_result()
            else:
                session.session_done()

    class StateCancelled(SessionState):
        @classmethod
        def process_msg(cls, session, msg):
            pass

    class StateUploadingFile(SessionState): pass
    class StateDone(SessionState): pass
    class StateFailed(SessionState): pass

    def async(func):
        def wrapper(self, runner, *args, **kwds):
            return runner.submit(func, self, *args, **kwds)
        return wrapper

    def __init__(self, runner, send_msg, remote_id):
        super().__init__()
        self.local_id = runner.generate_session_id()
        self.sender = self.Sender(send_msg, remote_id)
        self.runner = runner
        self.completed = False
        self.cancel_pending = False
        self.process = None
        self.__state = None
        self.note_time('session created')
        self.change_state(self.StateGetTask)

    def close(self):
        try:
            shutil.rmtree(self.include_path)
            os.rmdir(self.include_path)
        except Exception:
            pass

    class Sender:
        def __init__(self, send_msg, remote_id):
            self._send_msg = send_msg
            self._remote_id = remote_id

        def send_msg(self, data):
            self._send_msg([self._remote_id] + list(data))

    @property
    def state(self):
        return self.__state

    def change_state(self, state):
        if self.__state is not None:
            self.__state.exit_state(self)
        self.__state = state
        self.__state.enter_state(self)

    def compiler_id(self):
        return self.task.compiler_info.id

    def compiler_exe(self):
        return os.path.join(
            self.runner.compiler_repository().compiler_dir(self.compiler_id()),
            self.task.compiler_info.executable)

    def compile(self):
        self.change_state(self.StateRunningCompiler)
        if self.task.pch_file:
            self.runner.pch_repository().when_pch_is_available(
                    self.task.pch_file, self.__check_compiler_files)
        else:
            self.__check_compiler_files()

    def __check_compiler_files(self):
        self.runner.compiler_repository().when_compiler_is_ready(
            self.compiler_id(), self.__run_compiler)

    def __run_compiler(self):
        if self.cancel_pending:
            self.cancel_session()
            return
        self.cancel_selfdestruct()

        # Find compiler options.
        assert self.task.compiler_info.toolset == 'msvc'
        from buildpal.manager.compilers.msvc import MSVCCompiler
        compiler_options = MSVCCompiler

        tempdir = self.runner.header_repository().tempdir(id(self))
        obj_handle, self.object_file = tempfile.mkstemp(
            dir=tempdir, suffix='.obj')
        os.close(obj_handle)
        output = compiler_options.set_object_name_option(self.object_file)

        command = [self.compiler_exe(), output] + self.task.call
        file_overrides = {}

        if self.task.pch_file:
            assert self.pch_file is not None
            assert self.task.pch_header is not None
            file_overrides[self.task.pch_file[0]] = self.pch_file
            self.pch_file = self.task.pch_file[0]
            command.append(compiler_options.set_pch_file_option(self.pch_file))
            command.append(compiler_options.set_use_pch_option(
                self.task.pch_header))
            for include in self.task.forced_includes:
                command.append(compiler_options.set_forced_include_option(
                    include))

        include_dirs, src_loc = self.include_dirs_future.result()
        logging.debug("Include dirs:")
        for include in include_dirs:
            logging.debug(include)
        command.extend([compiler_options.set_include_option(incpath)
            for incpath in include_dirs])
        command.append(self.task.src_decorator + src_loc)

        self.note_time('ready for compile', 'prepare for compile')
        self.runner.run_compiler(self, command, tempdir, file_overrides,
            self.__compile_completed)

    def __compile_completed(self, future):
        self.note_time('compilation done', 'running compiler')
        try:
            stdout, stderr, retcode = future.result()
        except Exception as e:
            if self.state == self.StateRunningCompiler:
                self.change_state(self.StateFailed)
                tb = StringIO()
                tb.write("============================\n")
                tb.write("     SERVER TRACEBACK\n")
                tb.write("============================\n")
                traceback.print_exc(file=tb)
                tb.write("============================\n")
                tb.seek(0)
                logging.exception(e)
                self.sender.send_msg([b'SERVER_FAILED',
                        tb.read().encode()])
                self.session_done()
            else:
                assert self.state == self.StateCancelled
        else:
            if self.state == self.StateRunningCompiler:
                if retcode == 0:
                    self.change_state(self.StateWaitForConfirmation)
                durations_dict = dict((n, d) for e, (n, d) in self.time_durations())
                self.sender.send_msg([b'SERVER_DONE', pickle.dumps(
                    (retcode, stdout, stderr, durations_dict))])
                if retcode == 0:
                    self.reschedule_selfdestruct()
                else:
                    self.session_done()
            else:
                assert self.state == self.StateCancelled

    def session_done(self, from_selfdestruct=False):
        if from_selfdestruct and self.completed:
            return
        assert not self.completed
        if from_selfdestruct:
            self.sender.send_msg([b'TIMED_OUT'])
        else:
            self.cancel_selfdestruct()
        self.note_time('session completed', 'finishing session')
        self.runner.header_repository().session_complete(id(self))
        self.runner.terminate(self.local_id)
        self.close()
        self.completed = True

    def reschedule_selfdestruct(self):
        self.cancel_selfdestruct()
        self.selfdestruct = self.runner.scheduler().enter(60, 1,
            self.session_done, (True,))

    def cancel_selfdestruct(self):
        if hasattr(self, 'selfdestruct'):
            self.runner.scheduler().cancel(self.selfdestruct)
            del self.selfdestruct

    def send_result(self):
        def compress_one(filename):
            result = []
            size = 0
            with open(filename, 'rb') as file:
                compressed_gen = compress_file(file)
                for x in compressed_gen:
                    result.append((b'\x01', x))
                    size += len(x)
                result.append((b'\x00', b''))
                logging.debug("Sending '{}', size {}, raw {}.".format(filename, size, file.tell()))
            return result

        def compress_result():
            try:
                return compress_one(self.object_file)
            finally:
                os.remove(self.object_file)

        def send_compressed(future):
            for buffer in future.result():
                self.sender.send_msg(buffer)
            self.note_time('result sent', 'sending result')
            self.session_done()

        self.runner.async_run(compress_result).add_done_callback(
            send_compressed)

    def cancel_session(self):
        assert self.state != self.StateCancelled
        self.sender.send_msg([b'SESSION_CANCELLED'])
        self.change_state(self.StateCancelled)
        self.session_done()

    def process_msg(self, msg):
        assert not self.completed
        self.reschedule_selfdestruct()
        if msg[0] == b'CANCEL_SESSION':
            # Special care must be taken not to send cancellation confirmation
            # too early. Once it is sent, it must be final.
            # If a state does not have a 'process_msg' function this means
            # that no data will be sent while in this state. This kind of
            # state can send cancel confirmation directly.
            if self.state.can_be_cancelled and not hasattr(self.state, 'process_msg'):
                self.state.cancel(self)
                self.cancel_session()
            else:
            # Otherwise, state expects some data. We will wait for this data
            # to arrive and send cancel confirmation as a reply.
                self.cancel_pending = True
                return
        else:
            # Some states do not allow cancellation. For instance, Compiler and
            # PCH downloads. These parts are 'bigger' than this session, as some
            # other session might depend on this download.
            if self.cancel_pending and self.state.can_be_cancelled:
                self.cancel_session()
                return
            self.state.process_msg(self, msg)

    @async
    def prepare_include_dirs(self, new_files):
        result = self.runner.header_repository().prepare_dir(
            self.task.fqdn, id(self), new_files, self.task.include_dirs)
        self.note_time('include dir ready', 'preparing include dir')
        return result

class ServerProtocol(MessageProtocol):
    def __init__(self, runner):
        MessageProtocol.__init__(self)
        self.runner = runner

    def close(self):
        if self.transport:
            self.transport.write_eof()

    def process_msg(self, msg):
        session = None
        session_id, *msg = msg
        if session_id == b'NEW_SESSION':
            remote_id, *msg = msg
            session = CompileSession(self.runner, self.send_msg, remote_id.tobytes())
            self.runner.sessions[session.local_id] = session
        elif session_id == b'RESET':
            self.runner.finish(restart=True)
        elif session_id == b'SHUTDOWN':
            self.runner.finish()
        else:
            session = self.runner.sessions.get(session_id)
        if session:
            session.process_msg(msg)

class ProcessRunner:
    def __init__(self, limit, loop):
        self.limit = limit
        self.current = 0
        self.ready = asyncio.Event(loop=loop)
        self.loop = loop

    @asyncio.coroutine
    def subprocess_exec(self, session, args, cwd, file_maps):
        start = time()
        while self.current == self.limit:
            yield from self.ready.wait()
        self.ready.clear()
        assert self.current < self.limit
        compile_start = time()
        self.current += 1
        try:
            with OverrideCreateProcess(file_maps):
                session.process = yield from asyncio.create_subprocess_exec(*args,
                    cwd=cwd, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, loop=self.loop)
            stdout, stderr = yield from session.process.communicate()
            retcode = yield from session.process.wait()
        finally:
            session.process = None
            self.current -= 1
            self.ready.set()
        return stdout, stderr, retcode

class ServerRunner:
    def __init__(self, port, compile_slots):
        self.compile_slots = compile_slots
        self.port = port
        self.sessions = {}
        self.reset = False

        dir = os.path.join(tempfile.gettempdir(), "BuildPal", "Temp")
        os.makedirs(dir, exist_ok=True)
        self.scratch_dir = tempfile.mkdtemp(dir=dir)
        self.counter = 0

    def scheduler(self): return self._scheduler
    def misc_thread_pool(self): return self._misc_thread_pool
    def header_repository(self): return self._header_repository
    def pch_repository(self): return self._pch_repository
    def compiler_repository(self): return self._compiler_repository

    def generate_session_id(self):
        self.counter += 1
        return struct.pack('!I', self.counter)

    def terminate(self, session_id):
        del self.sessions[session_id]

    def async_run(self, callable, *args):
        return asyncio.async(self.loop.run_in_executor(self.misc_thread_pool(),
            callable, *args), loop=self.loop)

    def run_compiler(self, session, args, cwd, file_overrides, done_callback):
        file_maps = []
        if file_overrides:
            file_map = map_files.FileMap()
            for virtual_file, real_file in file_overrides.items():
                file_map.map_file(virtual_file, real_file)
            file_maps.append(file_map)
        file_maps.extend(self.header_repository().get_mappings(
            session.task.fqdn, id(session)))
        logging.debug("Running '{}'".format(args))
        asyncio.async(self.process_runner.subprocess_exec(session, args, cwd, file_maps),
            loop=self.loop).add_done_callback(done_callback)

    def run_event_loop(self, silent):
        @asyncio.coroutine
        def print_stats():
            if not silent:
                sys.stdout.write("Currently running {} tasks.\r".format(len(self.sessions)))
            self._scheduler.run(False)
            yield from asyncio.sleep(1, loop=self.loop)
            asyncio.async(print_stats(), loop=self.loop)

        asyncio.async(print_stats(), loop=self.loop)
        self.loop.run_forever()

    def finish(self, restart=False):
        self.keep_running = restart
        self.loop.stop()

    def run(self, terminator=None, silent=False):
        def protocol_factory():
            return ServerProtocol(self)

        while True:
            self.keep_running = False
            self.loop = asyncio.ProactorEventLoop()
            self.process_runner = ProcessRunner(self.compile_slots, self.loop)

            # Data shared between sessions.
            self._misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
            self._header_repository = HeaderRepository(self.scratch_dir)
            self._pch_repository = PCHRepository(self.scratch_dir)
            self._compiler_repository = CompilerRepository()
            self._scheduler = sched.scheduler()
            self.server = self.loop.run_until_complete(self.loop.create_server(
                protocol_factory, family=socket.AF_INET, port=self.port))
            if self.port == 0:
                self.port = self.server.sockets[0].getsockname()[1]

            beacon = Beacon(self.compile_slots, self.port)
            beacon.start()

            if not silent:
                print("Running server on 'localhost:{}'.".format(self.port))
                print("Using {} job slots.".format(self.compile_slots))

            try:
                def stop():
                    self.loop.stop()
                if terminator:
                    terminator.initialize(stop)
                self.run_event_loop(silent)
            finally:
                beacon.stop()
                self.server.close()
                self.loop.stop()
                self.loop.close()
                self.misc_thread_pool().shutdown()
                if not self.keep_running:
                    break
