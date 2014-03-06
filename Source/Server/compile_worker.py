from Common import SimpleTimer, MessageProtocol, compress_file
    
import asyncio

from io import BytesIO, StringIO
from multiprocessing import cpu_count
from time import sleep, time
from struct import pack
from concurrent.futures import ThreadPoolExecutor
from threading import Thread, Lock, current_thread
from subprocess import list2cmdline

from .header_repository import HeaderRepository
from .pch_repository import PCHRepository
from .compiler_repository import CompilerRepository
from .beacon import Beacon

import subprocess
import logging

import os
import pickle
import sched
import shutil
import signal
import socket
import struct
import sys
import traceback
import tempfile
import zipfile
import zlib
import queue
import map_files

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

class Popen(subprocess.Popen):
    def __init__(self, overrides, *args, **kwargs):
        assert sys.platform == "win32"
        self.overrides = overrides
        super(Popen, self).__init__(*args, **kwargs)

    def _execute_child(self, args, executable, preexec_fn, close_fds,
                        pass_fds, cwd, env,
                        startupinfo, creationflags, shell,
                        p2cread, p2cwrite,
                        c2pread, c2pwrite,
                        errread, errwrite,
                        unused_restore_signals, unused_start_new_session):
        """Execute program (MS Windows version)"""

        assert not pass_fds, "pass_fds not supported on Windows."

        if not isinstance(args, str):
            args = subprocess.list2cmdline(args)

        # Process startup details
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        if -1 not in (p2cread, c2pwrite, errwrite):
            startupinfo.dwFlags |= subprocess._winapi.STARTF_USESTDHANDLES
            startupinfo.hStdInput = p2cread
            startupinfo.hStdOutput = c2pwrite
            startupinfo.hStdError = errwrite

        if shell:
            startupinfo.dwFlags |= subprocess._winapi.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess._winapi.SW_HIDE
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            args = '{} /c "{}"'.format (comspec, args)
            if (subprocess._winapi.GetVersion() >= 0x80000000 or
                    os.path.basename(comspec).lower() == "command.com"):
                # Win9x, or using command.com on NT. We need to
                # use the w9xpopen intermediate program. For more
                # information, see KB Q150956
                # (http://web.archive.org/web/20011105084002/http://support.microsoft.com/support/kb/articles/Q150/9/56.asp)
                w9xpopen = self._find_w9xpopen()
                args = '"%s" %s' % (w9xpopen, args)
                # Not passing CREATE_NEW_CONSOLE has been known to
                # cause random failures on win9x.  Specifically a
                # dialog: "Your program accessed mem currently in
                # use at xxx" and a hopeful warning about the
                # stability of your system.  Cost is Ctrl+C won't
                # kill children.
                creationflags |= subprocess._winapi.CREATE_NEW_CONSOLE

        # Start the process
        try:
            if self.overrides:
                hp, ht, pid, tid = map_files.createProcess(executable, args,
                                            # no special security
                                            None, None,
                                            int(not close_fds),
                                            creationflags,
                                            env,
                                            cwd,
                                            startupinfo, self.overrides)
            else:
                hp, ht, pid, tid = subprocess._winapi.CreateProcess(executable, args,
                                            # no special security
                                            None, None,
                                            int(not close_fds),
                                            creationflags,
                                            env,
                                            cwd,
                                            startupinfo)
        except subprocess.pywintypes.error as e:
            # Translate pywintypes.error to WindowsError, which is
            # a subclass of OSError.  FIXME: We should really
            # translate errno using _sys_errlist (or similar), but
            # how can this be done from Python?
            raise subprocess.WindowsError(*e.args)
        finally:
            # Child is launched. Close the parent's copy of those pipe
            # handles that only the child should have open.  You need
            # to make sure that no handles to the write end of the
            # output pipe are maintained in this process or else the
            # pipe will not close when the child process exits and the
            # ReadFile will hang.
            if p2cread != -1:
                p2cread.Close()
            if c2pwrite != -1:
                c2pwrite.Close()
            if errwrite != -1:
                errwrite.Close()
            if hasattr(self, '_devnull'):
                os.close(self._devnull)

        # Retain the process handle, but close the thread handle
        self._child_created = True
        self._handle = subprocess.Handle(hp)
        self.pid = pid
        subprocess._winapi.CloseHandle(ht)

class CompileSession:
    def async(func):
        def wrapper(self, runner, *args, **kwds):
            return runner.submit(func, self, *args, **kwds)
        return wrapper

    def __init__(self, runner, send_msg, remote_id):
        self.local_id = runner.generate_unique_id()
        self.sender = self.Sender(send_msg, remote_id)
        self.runner = runner
        self.include_path = tempfile.mkdtemp(dir=self.runner.scratch_dir)
        self.times = {}
        self.compiler_state_lock = Lock()
        self.completed = False
        self.cancel_pending = False
        self.__state = None
        self.change_state(self.StateGetTask)

    def __del__(self):
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
        return self.task['compiler_info']['id']

    def compiler_exe(self):
        return os.path.join(
            self.runner.compiler_repository().compiler_dir(self.compiler_id()),
            self.task['compiler_info']['executable'])

    def compile(self):
        self.change_state(self.StateRunningCompiler)
        if self.task['pch_file']:
            self.runner.pch_repository().when_pch_is_available(
                    self.task['pch_file'], self.__check_compiler_files)
        else:
            self.__check_compiler_files()

    def __check_compiler_files(self):
        self.runner.compiler_repository().when_compiler_is_available(
            self.compiler_id(), self.__run_compiler)

    def __run_compiler(self):
        # Before we actually run the expensive compile operation, make sure that
        # we have not been cancelled yet.
        if self.cancel_pending:
            self.cancel_session()
            return
        self.cancel_selfdestruct()
        asyncio.async(self.runner.loop.run_in_executor(
            self.runner.compile_thread_pool(),
            self.__async_run_compiler,
            time()), loop=self.runner.loop).add_done_callback(
                self.__compile_completed)

    def __async_run_compiler(self, start_time):
        self.times['waiting for job slot'] = time() - start_time
        obj_handle, obj_name= tempfile.mkstemp(
            dir=self.runner.scratch_dir, suffix='.obj')
        os.close(obj_handle)

        self.source_file = os.path.join(self.include_path, self.src_loc)

        compiler_info = self.task['compiler_info']
        output = compiler_info['set_object_name'].format(obj_name)
        pch_switch = []
        overrides = {}
        if self.task['pch_file']:
            # TODO: MSVC specific, remove from here.
            if '/GL' in self.task['call']:
                # In case /GL command line option is present, PCH file will
                # not be fully resolved during compilation. Instead,
                # resulting .obj file will contain a reference to it, and
                # consequently PCH file will be needed at link phase.
                # The problem we face is that PCH path on slave machine
                # will not be the same as the client machine. This is why
                # we mimic the client's PCH path on the slave.
                # The filesystem hook used here is implemented using
                # DLL injection/API hooking, so is entirely in userland.
                # It affects compiler performance, so is used only when
                # absolutely necessary.
                overrides[self.task['pch_file'][0]] = self.pch_file
                self.pch_file = self.task['pch_file'][0]
            assert self.pch_file is not None
            assert os.path.exists(self.pch_file)
            pch_switch.append(compiler_info['set_pch_file'].format(
                self.pch_file
            ))

        include_dirs = self.include_dirs_future.result()
        includes = [compiler_info['set_include_option'].format(incpath)
            for incpath in include_dirs]
        command = ([self.compiler_exe()] + self.task['call'] + pch_switch +
            includes + [output, self.source_file])

        start = time()
        with self.compiler_state_lock:
            self.process = Popen(overrides, command, cwd=self.include_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout, stderr), retcode, done = self.process.communicate(), \
            self.process.returncode, time()
        with self.compiler_state_lock:
            del self.process
        self.times['compiler time'] = done - start
        return obj_name, stdout, stderr, retcode

    def __compile_completed(self, future):
        try:
            obj_name, stdout, stderr, retcode = future.result()
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
                self.sender.send_msg([b'SERVER_FAILED',
                        tb.read().encode()])
                self.session_done()
            else:
                assert self.state == self.StateCancelled
        else:
            if self.state == self.StateRunningCompiler:
                if retcode == 0:
                    self.change_state(self.StateWaitForConfirmation)
                    self.object_file = obj_name
                self.sender.send_msg([b'SERVER_DONE', pickle.dumps(
                    (retcode, stdout, stderr, self.times))])
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
        self.runner.terminate(self.local_id)
        self.completed = True

    def reschedule_selfdestruct(self):
        self.cancel_selfdestruct()
        self.selfdestruct = self.runner.scheduler().enter(60, 1,
            self.session_done, (True,))

    def cancel_selfdestruct(self):
        if hasattr(self, 'selfdestruct'):
            self.runner.scheduler().cancel(self.selfdestruct)
            del self.selfdestruct

    def send_threadsafe(self, msg):
        self.runner.loop.call_soon_threadsafe(
            self.sender.send_msg, msg)

    def send_object_file(self, obj_file):
        def send_compressed_file():
            fh = os.open(obj_file, os.O_RDONLY | os.O_BINARY |
                os.O_NOINHERIT)
            try:
                with os.fdopen(fh, 'rb') as file:
                    for buffer in compress_file(file):
                        self.send_threadsafe([b'\x01', buffer])
                    self.send_threadsafe([b'\x00', b''])
            finally:
                os.remove(obj_file)

        def complete_session(future):
            future.result()
            self.session_done()

        self.runner.loop.run_in_executor(self.runner.misc_thread_pool(),
            send_compressed_file).add_done_callback(complete_session)

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
    def prepare_include_dirs(self, fqdn, new_files):
        shared_prepare_dir_timer = SimpleTimer()
        result = self.runner.header_repository().prepare_dir(fqdn, new_files,
            self.repo_transaction_id, self.include_path)
        self.times['prepare include directory'] = shared_prepare_dir_timer.get()
        del shared_prepare_dir_timer
        return result

class ServerProtocol(MessageProtocol):
    def __init__(self, runner):
        MessageProtocol.__init__(self)
        self.runner = runner

    def process_msg(self, msg):
        session_id, *msg = msg
        if session_id == b'NEW_SESSION':
            remote_id, *msg = msg
            session = CompileSession(self.runner, self.send_msg, remote_id.tobytes())
            self.runner.sessions[session.local_id] = session
        else:
            session = self.runner.sessions.get(session_id)
        if session:
                session.process_msg(msg)


class CompileWorker:
    def __init__(self, port, compile_slots):
        self.__port = port
        self.__compile_slots = compile_slots
        self.sessions = {}

        dir = os.path.join(tempfile.gettempdir(), "BuildPal", "Temp")
        os.makedirs(dir, exist_ok=True)
        self.scratch_dir = tempfile.mkdtemp(dir=dir)
        self.counter = 0

        # Data shared between sessions.
        self.__compile_thread_pool = ThreadPoolExecutor(self.__compile_slots)
        self.__misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
        self.__header_repository = HeaderRepository(self.scratch_dir)
        self.__pch_repository = PCHRepository(self.scratch_dir)
        self.__compiler_repository = CompilerRepository()
        self.__scheduler = sched.scheduler()

    def scheduler(self): return self.__scheduler
    def compile_thread_pool(self): return self.__compile_thread_pool
    def misc_thread_pool(self): return self.__misc_thread_pool
    def header_repository(self): return self.__header_repository
    def pch_repository(self): return self.__pch_repository
    def compiler_repository(self): return self.__compiler_repository

    def generate_unique_id(self):
        self.counter += 1
        return struct.pack('!I', self.counter)

    def terminate(self, session_id):
        del self.sessions[session_id]

    def run_event_loop(self):
        @asyncio.coroutine
        def print_stats():
            sys.stdout.write("Currently running {} tasks.\r".format(len(self.sessions)))
            self.__scheduler.run(False)
            yield from asyncio.sleep(1, loop=self.loop)
            asyncio.async(print_stats(), loop=self.loop)

        asyncio.async(print_stats(), loop=self.loop)
        self.loop.run_forever()

    def run(self):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        self.loop = asyncio.ProactorEventLoop()
        def protocol_factory():
            return ServerProtocol(self)
        self.server = self.loop.run_until_complete(self.loop.create_server(
            protocol_factory, family=socket.AF_INET, port=self.__port))
        if self.__port == 0:
            self.__port = self.server.sockets[0].getsockname()[1]

        beacon = Beacon(self.__compile_slots, self.__port)
        beacon.start(multicast_address='239.192.29.71', multicast_port=51134)

        print("Running server on 'localhost:{}'.".format(self.__port))
        print("Using {} job slots.".format(self.__compile_slots))

        try:
            event_loop_thread = Thread(target=self.run_event_loop)
            event_loop_thread.start()
            while True:
                sleep(1)
        finally:
            beacon.stop()
            self.server.close()
            self.loop.stop()
            event_loop_thread.join()
            self.loop.close()

    def shutdown(self):
        self.__compile_thread_pool.shutdown()
        self.__misc_thread_pool.shutdown()

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
            # Determine headers which are missing
            missing_files_timer = SimpleTimer()
            missing_files, session.repo_transaction_id = \
                session.runner.header_repository().missing_files(
                session.task['fqdn'], session.task['filelist'])
            session.times['determine missing files'] = missing_files_timer.get()
            # Determine if we have this compiler
            session.compiler_required = session.runner.compiler_repository(
                ).compiler_required(session.compiler_id())

            # Determine whether we need pch PCH file.
            if session.task['pch_file'] is None:
                session.pch_required = False
            else:
                session.pch_file, session.pch_required = \
                    session.runner.pch_repository().register_file(
                        session.task['pch_file'])
            session.sender.send_msg([session.local_id, b'MISSING_FILES',
                pickle.dumps((missing_files, session.compiler_required,
                session.pch_required))])
            session.change_state(CompileSession.StateDownloadMissingHeaders)

    class StateDownloadMissingHeaders(SessionState):
        @classmethod
        def process_msg(cls, session, msg):
            assert msg[0] == b'TASK_FILES'
            fqdn = session.task['fqdn']
            new_files = pickle.loads(msg[1].memory())
            session.src_loc = msg[2].tobytes().decode()
            session.waiting_for_manager_data = SimpleTimer()
            session.include_dirs_future = session.prepare_include_dirs(
                session.runner.misc_thread_pool(), fqdn, new_files)
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
            session.compiler_data.write(data)
            if more == b'\x00':
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
            handle = os.open(session.pch_file, os.O_CREAT | os.O_WRONLY |
                os.O_NOINHERIT)
            session.pch_timer = SimpleTimer()
            session.pch_desc = os.fdopen(handle, 'wb')
            session.pch_decompressor = zlib.decompressobj()

        @classmethod
        def process_msg(cls, session, msg):
            more, data = msg
            session.pch_desc.write(session.pch_decompressor.decompress(data.memory()))
            if more == b'\x00':
                session.pch_desc.write(session.pch_decompressor.flush())
                session.times['upload precompiled header'] = session.pch_timer.get()
                session.runner.pch_repository().file_completed(session.task['pch_file'])
                session.compile()

        @classmethod
        def exit_state(cls, session):
            session.pch_desc.close()
            del session.pch_desc
            del session.pch_decompressor

    class StateRunningCompiler(SessionState):
        can_be_cancelled = True

        @classmethod
        def cancel(cls, session):
            with session.compiler_state_lock:
                if hasattr(session, 'process'):
                    session.process.terminate()

    class StateWaitForConfirmation(SessionState):
        can_be_cancelled = True

        @classmethod
        def process_msg(cls, session, msg):
            tag, verdict = msg
            assert tag == b'SEND_CONFIRMATION'
            if verdict == b'\x01':
                session.change_state(CompileSession.StateUploadingFile)
                session.send_object_file(session.object_file)
            else:
                session.session_done()

    class StateUploadingFile(SessionState): pass
    class StateDone(SessionState): pass
    class StateFailed(SessionState): pass
    class StateCancelled(SessionState): pass
