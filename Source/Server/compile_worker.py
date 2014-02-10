from Common import send_compressed_file, SimpleTimer, \
    create_socket, recv_multipart, \
    bind_to_random_port

from io import BytesIO, StringIO
from multiprocessing import Process, cpu_count
from time import sleep, time
from struct import pack
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread
from subprocess import list2cmdline

from .header_repository import HeaderRepository
from .pch_repository import PCHRepository
from .compiler_repository import CompilerRepository
from .beacon import Beacon

import subprocess
import logging

import os
import pickle
import signal
import shutil
import sched
import sys
import traceback
import tempfile
import zipfile
import zlib
import zmq
import queue
import map_files

zmq_ctx = zmq.Context()

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
    STATE_GET_TASK = 0
    STATE_DOWNLOADING_MISSING_HEADERS = 1
    STATE_DOWNLOADING_COMPILER = 2
    STATE_DOWNLOADING_PCH = 3
    STATE_RUNNING_COMPILER = 4
    STATE_WAIT_FOR_CONFIRMATION = 5
    STATE_DONE = 6
    STATE_FAILED = 7
    STATE_CANCELLED = 8

    def async(func):
        def wrapper(self, runner, *args, **kwds):
            return runner.submit(func, self, *args, **kwds)
        return wrapper

    def __init__(self, runner, socket, id):
        self.id = id
        self.socket = socket
        self.runner = runner
        self.state = self.STATE_GET_TASK
        temp_dir = os.path.join(tempfile.gettempdir(), "BuildPal", "Temp")
        os.makedirs(temp_dir, exist_ok=True)
        self.include_path = tempfile.mkdtemp(dir=temp_dir)
        self.times = {}
        self.compiler_state_lock = Lock()
        self.completed = False

    def __del__(self):
        try:
            shutil.rmtree(self.include_path)
            os.rmdir(self.include_path)
        except Exception:
            pass

    class Sender:
        def __init__(self, id, socket=None):
            if not socket:
                self.socket = create_socket(zmq_ctx, zmq.DEALER)
                self.socket.connect('inproc://sessions_socket')
                self.close_socket = True
            else:
                self.socket = socket
                self.close_socket = False
            self.id = id

        def send(self, data, copy=False):
            self.socket.send_multipart([self.id, data], copy=copy)

        def send_pyobj(self, data, copy=False):
            self.socket.send_multipart([self.id, pickle.dumps(data)], copy=copy)

        def send_multipart(self, data, copy=False):
            self.socket.send_multipart([self.id] + list(data), copy=copy)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()

        def close(self):
            if self.close_socket:
                self.socket.close()

    def run_compiler(self):
        self.state = self.STATE_RUNNING_COMPILER
        self.cancel_autodestruct()
        self.runner.compile_thread_pool().submit(
            self.async_run_compiler, time())

    def compiler_id(self):
        return self.task['compiler_info']['id']

    def compiler_exe(self):
        return os.path.join(
            self.runner.compiler_repository().compiler_dir(self.compiler_id()),
            self.task['compiler_info']['executable'])

    def sender(self, other_thread=True):
        return self.Sender(self.id, None if other_thread else self.socket)

    def async_run_compiler(self, start_time):
        self.times['async_compiler_delay'] = time() - start_time
        try:
            object_file_handle, object_file_name = tempfile.mkstemp(
                suffix='.obj')
            os.close(object_file_handle)

            self.source_file = os.path.join(self.include_path, self.src_loc)

            compiler_info = self.task['compiler_info']
            output = compiler_info['set_object_name'].format(object_file_name)
            pch_switch = []
            overrides = {}
            if self.task['pch_file']:
                if '/GL' in self.task['call']:
                    # TODO: MSVC specific, remove from here.
                    # In case /GL command line option is present, PCH file will
                    # not be fully resolved during compilation. Instead,
                    # resulting .obj file will have a reference to it, and
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
                while not self.runner.pch_repository().file_arrived(
                    *self.task['pch_file']):
                    # The PCH file is being downloaded by another session.
                    # This could be made prettier by introducing another state
                    # in this state machine. However, wake-up event for that
                    # state would require inter-session communication.
                    # Just not worth the additional complexity.
                    sleep(1)

            while not self.runner.compiler_repository().has_compiler(self.compiler_id()):
                # Compiler is being downloaded by another session.
                # Similar to the PCH hack above.
                sleep(1)

            include_dirs = self.include_dirs_future.result()
            includes = [compiler_info['set_include_option'].format(incpath)
                for incpath in include_dirs]
            command = ([self.compiler_exe()] + self.task['call'] + pch_switch +
                includes + [output, self.source_file])

            start = time()
            with self.compiler_state_lock:
                if self.state == self.STATE_CANCELLED:
                    return
                self.process = Popen(overrides, command, cwd=self.include_path,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (stdout, stderr), retcode, done = self.process.communicate(), \
                self.process.returncode, time()
            with self.compiler_state_lock:
                del self.process
            self.times['compiler'] = done - start
            self.times['server_time'] = self.server_time_timer.get()
            del self.server_time_timer
        except Exception as e:
            with self.compiler_state_lock:
                if self.state == self.STATE_RUNNING_COMPILER:
                    self.state = self.STATE_FAILED
                    tb = StringIO()
                    tb.write("============================\n")
                    tb.write("     SERVER TRACEBACK\n")
                    tb.write("============================\n")
                    traceback.print_exc(file=tb)
                    tb.write("============================\n")
                    tb.seek(0)
                    with self.sender() as sender:
                        sender.send_multipart([b'SERVER_FAILED',
                            tb.read().encode()])
                    self.session_done()
                else:
                    assert self.state == self.STATE_CANCELLED
        else:
            with self.compiler_state_lock:
                if self.state == self.STATE_RUNNING_COMPILER:
                    with self.sender() as sender:
                        if retcode == 0:
                            self.state = self.STATE_WAIT_FOR_CONFIRMATION
                            self.object_file = object_file_name
                        sender.send_multipart([b'SERVER_DONE', pickle.dumps(
                            (retcode, stdout, stderr, self.times))])
                        if retcode == 0:
                            self.reschedule_selfdestruct()
                        else:
                            self.session_done()
                else:
                    assert self.state == self.STATE_CANCELLED
        finally:
            x.close()

    def session_done(self, from_selfdestruct=False):
        assert not hasattr(self, 'selfdestruct') or from_selfdestruct
        assert not self.completed
        self.completed = True
        self.runner.terminate(self.id)

    def reschedule_selfdestruct(self):
        self.cancel_autodestruct()
        self.selfdestruct = self.runner.scheduler().enter(60, 1, self.session_done,
            (True,))

    def cancel_autodestruct(self):
        if hasattr(self, 'selfdestruct'):
            self.runner.scheduler().cancel(self.selfdestruct)
            del self.selfdestruct

    def process_msg(self, msg):
        self.reschedule_selfdestruct()
        if msg[0] == b'CANCEL_SESSION':
            if self.completed:
                # We are already dead, just don't know it yet.
                return
            if self.state == self.STATE_RUNNING_COMPILER:
                with self.compiler_state_lock:
                    self.state = self.STATE_CANCELLED
                    if hasattr(self, 'process'):
                        self.process.terminate()
            with self.sender(False) as sender:
                sender.send(b'SESSION_CANCELLED')
            self.cancel_autodestruct()
            self.session_done()

        elif self.state == self.STATE_GET_TASK:
            self.server_time_timer = SimpleTimer()
            self.waiting_for_header_list = SimpleTimer()
            assert len(msg) == 2
            assert msg[0] == b'SERVER_TASK'
            self.task = pickle.loads(msg[1])
            # Determine headers which are missing
            missing_files_timer = SimpleTimer()
            missing_files, self.repo_transaction_id = \
                self.runner.header_repository().missing_files(self.task['fqdn'],
                self.task['filelist'])
            self.times['process_hdr_list'] = missing_files_timer.get()
            # Determine if we have this compiler
            self.compiler_required = not \
                self.runner.compiler_repository().has_compiler(self.compiler_id())

            # Determine whether we need pch PCH file.
            if self.task['pch_file'] is None:
                self.pch_required = False
            else:
                self.pch_file, self.pch_required = \
                    self.runner.pch_repository().register_file(
                    *self.task['pch_file'])
            with self.sender(False) as sender:
                sender.send_multipart([b'MISSING_FILES', pickle.dumps(
                    (missing_files, self.compiler_required,
                    self.pch_required))])
            self.state = self.STATE_DOWNLOADING_MISSING_HEADERS
        elif self.state == self.STATE_DOWNLOADING_MISSING_HEADERS:
            assert msg[0] == b'TASK_FILES'
            fqdn = self.task['fqdn']
            new_files = pickle.loads(zlib.decompress(msg[1]))
            self.src_loc = msg[2].tobytes().decode()
            self.waiting_for_manager_data = SimpleTimer()
            self.include_dirs_future = self.prepare_include_dirs(
                self.runner.misc_thread_pool(), fqdn, new_files)
            if self.compiler_required:
                self.state = self.STATE_DOWNLOADING_COMPILER
                self.compiler_data = BytesIO()
            elif self.pch_required:
                self.state = self.STATE_DOWNLOADING_PCH
                handle = os.open(self.pch_file, os.O_CREAT | os.O_WRONLY |
                    os.O_NOINHERIT)
                self.pch_desc = os.fdopen(handle, 'wb')
                self.pch_decompressor = zlib.decompressobj()
            else:
                self.run_compiler()
        elif self.state == self.STATE_DOWNLOADING_COMPILER:
            more, data = msg
            self.compiler_data.write(data)
            if more == b'\x00':
                self.compiler_data.seek(0)
                dir = self.runner.compiler_repository().compiler_dir(
                    self.compiler_id())
                os.makedirs(dir, exist_ok=True)
                with zipfile.ZipFile(self.compiler_data) as zip:
                    zip.extractall(path=dir)
                del self.compiler_data
                self.runner.compiler_repository().set_compiler_ready(self.compiler_id())
                if self.pch_required:
                    self.state = self.STATE_DOWNLOADING_PCH
                    handle = os.open(self.pch_file, os.O_CREAT | os.O_WRONLY | os.O_NOINHERIT)
                    self.pch_desc = os.fdopen(handle, 'wb')
                    self.pch_decompressor = zlib.decompressobj()
                else:
                    self.run_compiler()
        elif self.state == self.STATE_DOWNLOADING_PCH:
            more, data = msg
            self.pch_desc.write(self.pch_decompressor.decompress(data))
            if more == b'\x00':
                self.pch_desc.write(self.pch_decompressor.flush())
                self.pch_desc.close()
                del self.pch_desc
                del self.pch_decompressor
                self.runner.pch_repository().file_completed(*self.task['pch_file'])
                self.run_compiler()
        elif self.state == self.STATE_WAIT_FOR_CONFIRMATION:
            self.cancel_autodestruct()
            tag, verdict = msg
            assert tag == b'SEND_CONFIRMATION'
            if verdict == b'\x01':
                fh = os.open(self.object_file, os.O_RDONLY | os.O_BINARY |
                    os.O_NOINHERIT)
                with os.fdopen(fh, 'rb') as obj, self.sender(False) as sender:
                    send_compressed_file(sender.send_multipart, obj, copy=False)
                os.remove(self.object_file)
            self.session_done()
        else:
            raise Exception("Invalid state.")

    @async
    def prepare_include_dirs(self, fqdn, new_files):
        shared_prepare_dir_timer = SimpleTimer()
        result = self.runner.header_repository().prepare_dir(fqdn, new_files, self.repo_transaction_id, self.include_path)
        self.times['shared_prepare_dir'] = shared_prepare_dir_timer.get()
        del shared_prepare_dir_timer
        return result

class CompileWorker:
    def __init__(self, port, compile_slots):
        self.__port = port
        self.__compile_slots = compile_slots
        self.sessions = {}

        # Data shared between sessions.
        self.__compile_thread_pool = ThreadPoolExecutor(self.__compile_slots)
        self.__misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
        self.__header_repository = HeaderRepository()
        self.__pch_repository = PCHRepository()
        self.__compiler_repository = CompilerRepository()
        self.__scheduler = sched.scheduler()

    def scheduler(self): return self.__scheduler
    def compile_thread_pool(self): return self.__compile_thread_pool
    def misc_thread_pool(self): return self.__misc_thread_pool
    def header_repository(self): return self.__header_repository
    def pch_repository(self): return self.__pch_repository
    def compiler_repository(self): return self.__compiler_repository

    def terminate(self, id):
        if id in self.sessions:
            del self.sessions[id]

    def run(self):
        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        client_socket = create_socket(zmq_ctx, zmq.ROUTER)
        if self.__port == 0:
            self.__port = bind_to_random_port(client_socket)
            self.__address = "tcp://*:{}".format(self.__port)
        else:
            self.__address = "tcp://*:{}".format(self.__port)
            client_socket.bind(self.__address)

        session_socket = create_socket(zmq_ctx, zmq.DEALER)
        session_socket.bind('inproc://sessions_socket')

        poller = zmq.Poller()
        poller.register(client_socket, zmq.POLLIN)
        poller.register(session_socket, zmq.POLLIN)

        print("Running server on '{}'.".format(self.__address))
        print("Using {} job slots.".format(self.__compile_slots))

        beacon = Beacon(self.__compile_slots, self.__port)
        beacon.start(multicast_address='239.192.29.71', multicast_port=51134)

        try:
            while True:
                sys.stdout.write("Currently running {} tasks.\r".format(len(self.sessions)))

                # Run any scheduled tasks.
                self.__scheduler.run(False)

                for sock, event in dict(poller.poll(1000)).items():
                    assert event == zmq.POLLIN
                    if sock is client_socket:
                        client_id, *msg = recv_multipart(client_socket)
                        if len(msg) == 1 and msg[0] == b'PING':
                            client_socket.send_multipart([client_id, b'PONG'])
                            continue
                        elif not client_id in self.sessions:
                            session = CompileSession(self, client_socket, client_id)
                            self.sessions[client_id] = session
                        else:
                            session = self.sessions[client_id]
                        session.process_msg(msg)
                    else:
                        assert sock is session_socket
                        client_socket.send_multipart(recv_multipart(session_socket))
        finally:
            beacon.stop()

    def shutdown(self):
        self.__compile_thread_pool.shutdown()
        self.__misc_thread_pool.shutdown()
