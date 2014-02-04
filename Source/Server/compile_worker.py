from Common import send_compressed_file, SimpleTimer, \
    create_socket, recv_multipart, \
    bind_to_random_port

from io import BytesIO, StringIO
from multiprocessing import Process, cpu_count
from time import sleep, time
from struct import pack
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread

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
    STATE_DONE = 1
    STATE_SENDING_MISSING_FILES = 2
    STATE_WAITING_FOR_COMPILER = 3
    STATE_CHECK_PCH_TAG = 4
    STATE_GET_PCH_DATA = 5
    STATE_FAILED = 6

    def verify(self, future):
        try:
            future.result()
        except Exception as e:
            self.process_failure(e)
            self.cancel_autodestruct()
            self.session_done()

    def async(verify=True):
        def async_helper(func):
            def wrapper(self, runner, *args, **kwds):
                future = runner.submit(func, self, *args, **kwds)
                if verify:
                    future.add_done_callback(self.verify)
                return future
            return wrapper
        return async_helper

    def process_failure(self, exception):
        tb = StringIO()
        traceback.print_exc(file=tb)
        tb.seek(0)
        self.state = self.STATE_FAILED
        sender = self.Sender(self.id)
        sender.send_multipart([b'SERVER_FAILED', tb.read().encode()])
        sender.disconnect()

    def __init__(self, pch_repository, header_repository, compiler_repository,
                 task_counter, checksums, compile_thread_pool, misc_thread_pool,
                 scheduler):
        self.state = self.STATE_GET_TASK
        self.task_counter = task_counter
        self.compiler_repository = compiler_repository
        self.header_repository = header_repository
        self.pch_repository = pch_repository
        temp_dir = os.path.join(tempfile.gettempdir(), "DistriBuild", "Temp")
        os.makedirs(temp_dir, exist_ok=True)
        self.include_path = tempfile.mkdtemp(dir=temp_dir)
        self.checksums = checksums
        self.times = {}
        self.compile_thread_pool = compile_thread_pool
        self.misc_thread_pool = misc_thread_pool
        self.scheduler = scheduler

    def __del__(self):
        try:
            shutil.rmtree(self.include_path)
            os.rmdir(self.include_path)
        except Exception:
            pass

    class Sender:
        def __init__(self, id):
            self.socket = create_socket(zmq_ctx, zmq.DEALER)
            self.id = id
            self.socket.connect('inproc://sessions_socket')

        def send(self, data, copy=False):
            self.socket.send_multipart([self.id, data], copy=copy)

        def send_pyobj(self, data, copy=False):
            self.socket.send_multipart([self.id, pickle.dumps(data)], copy=copy)

        def send_multipart(self, data, copy=False):
            self.socket.send_multipart([self.id] + list(data), copy=copy)

        def disconnect(self):
            self.socket.close()

    def run_compiler(self):
        self.cancel_autodestruct()
        self.compile_thread_pool.submit(
            self.async_run_compiler, time()).add_done_callback(
            self.verify)

    def async_run_compiler(self, start_time):
        self.times['async_compiler_delay'] = time() - start_time
        try:
            object_file_handle, object_file_name = tempfile.mkstemp(suffix='.obj')
            os.close(object_file_handle)

            compiler_prep = time()
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
                while not self.pch_repository.file_arrived(
                    *self.task['pch_file']):
                    # The PCH file is being downloaded by another session.
                    # This could be made prettier by introducing another state
                    # in this state machine. However, wake-up event for that
                    # state would require inter-session communication.
                    # Just not worth the additional complexity.
                    sleep(1)

            while not self.compiler_repository.has_compiler(self.compiler_id):
                # Compiler is being downloaded by another session.
                # Similar to the PCH hack above.
                sleep(1)

            include_dirs = self.include_dirs_future.result()
            includes = [compiler_info['set_include_option'].format(incpath) for incpath in include_dirs]
            start = time()
            self.times['compiler_prep'] = start - compiler_prep
            command = (self.task['call'] + pch_switch +
                includes + [output, self.source_file])
            retcode, stdout, stderr = self.compiler(command,
                self.include_path, overrides)
            done = time()
            self.times['compiler'] = done - start
            self.times['server_time'] = self.server_time_timer.get()
            del self.server_time_timer
        except Exception as e:
            self.process_failure(e)
        else:
            sender = self.Sender(self.id)
            sender.send_multipart([b'SERVER_DONE', pickle.dumps((retcode,
                stdout, stderr, self.times))])
            if retcode == 0:
                fh = os.open(object_file_name, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
                with os.fdopen(fh, 'rb') as obj:
                    send_compressed_file(sender.send_multipart, obj, copy=False)
            sender.disconnect()
        finally:
            self.session_done()
            os.remove(object_file_name)

    def compiler_ready(self):
        assert hasattr(self, 'compiler_id')
        self.compiler_exe = os.path.join(
            self.compiler_repository.compiler_dir(self.compiler_id),
            self.task['compiler_info']['executable'])
        def spawn_compiler(command, cwd, overrides={}):
            command[0] = self.compiler_exe
            with Popen(overrides, command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        self.compiler = spawn_compiler
        if self.task['pch_file'] is None:
                self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                self.run_compiler()
        else:
            self.state = self.STATE_CHECK_PCH_TAG

    def session_done(self):
        self.terminate()
        self.task_counter.dec()

    def prolong_lifetime(self):
        self.cancel_autodestruct()
        self.selfdestruct = self.scheduler.enter(60, 1, self.session_done)

    def cancel_autodestruct(self):
        if hasattr(self, 'selfdestruct'):
            self.scheduler.cancel(self.selfdestruct)
            del self.selfdestruct

    def process_msg(self, msg):
        self.prolong_lifetime()
        try:
            sender = self.Sender(self.id)
            if self.state == self.STATE_GET_TASK:
                self.task_counter.inc()
                self.server_time_timer = SimpleTimer()
                self.waiting_for_header_list = SimpleTimer()
                assert len(msg) == 2
                assert msg[0] == b'SERVER_TASK'
                self.task = pickle.loads(msg[1])
                self.compiler_id = self.task['compiler_info']['id']
                fqdn = self.task['fqdn']
                filelist = self.task['filelist']
                missing_files_timer = SimpleTimer()
                missing_files, self.repo_transaction_id = self.header_repository.missing_files(fqdn, filelist)
                self.times['process_hdr_list'] = missing_files_timer.get()
                sender.send_multipart([b'MISSING_FILES', pickle.dumps(missing_files)])
                self.state = self.STATE_SENDING_MISSING_FILES
            elif self.state == self.STATE_SENDING_MISSING_FILES:
                assert msg[0] == b'TASK_FILES'
                fqdn = self.task['fqdn']
                new_files = pickle.loads(zlib.decompress(msg[1]))
                self.src_loc = msg[2].tobytes().decode()
                self.waiting_for_manager_data = SimpleTimer()
                self.include_dirs_future = self.prepare_include_dirs(self.misc_thread_pool, fqdn, new_files)
                has_compiler = self.compiler_repository.has_compiler(self.compiler_id)
                if has_compiler is None:
                    # Never heard of it.
                    sender.send(b'NEED_COMPILER')
                    self.state = self.STATE_WAITING_FOR_COMPILER
                    self.compiler_data = BytesIO()
                else:
                    sender.send(b'READY')
                    self.compiler_ready()
            elif self.state == self.STATE_WAITING_FOR_COMPILER:
                more, data = msg
                self.compiler_data.write(data)
                if more == b'\x00':
                    self.compiler_data.seek(0)
                    with zipfile.ZipFile(self.compiler_data) as zip:
                        zip.extractall(path=self.compiler_repository.compiler_dir(self.compiler_id))
                    del self.compiler_data
                    self.compiler_repository.set_compiler_ready(self.compiler_id)
                    self.compiler_ready()
            elif self.state == self.STATE_CHECK_PCH_TAG:
                tag = msg[0]
                assert tag == b'NEED_PCH_FILE'
                self.pch_file, required = self.pch_repository.register_file(
                    *self.task['pch_file'])
                if required:
                    sender.send(b'YES')
                    if not os.path.exists(os.path.dirname(self.pch_file)):
                        os.makedirs(os.path.dirname(self.pch_file), exist_ok=True)
                    handle = os.open(self.pch_file, os.O_CREAT | os.O_WRONLY | os.O_NOINHERIT)
                    self.pch_desc = os.fdopen(handle, 'wb')
                    self.pch_decompressor = zlib.decompressobj()
                    self.state = self.STATE_GET_PCH_DATA
                else:
                    sender.send(b'NO')
                    self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                    self.run_compiler()
            elif self.state == self.STATE_GET_PCH_DATA:
                more, data = msg
                self.pch_desc.write(self.pch_decompressor.decompress(data))
                if more == b'\x00':
                    self.pch_desc.write(self.pch_decompressor.flush())
                    self.pch_desc.close()
                    del self.pch_desc
                    del self.pch_decompressor
                    self.pch_repository.file_completed(*self.task['pch_file'])
                    self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                    self.run_compiler()
            else:
                raise Exception("Invalid state.")
        finally:
            sender.disconnect()

    @async(verify=False)
    def prepare_include_dirs(self, fqdn, new_files):
        shared_prepare_dir_timer = SimpleTimer()
        result = self.header_repository.prepare_dir(fqdn, new_files, self.repo_transaction_id, self.include_path)
        self.times['shared_prepare_dir'] = shared_prepare_dir_timer.get()
        del shared_prepare_dir_timer
        return result

class CompileWorker:
    def __init__(self, port, compile_slots):
        self.__port = port
        self.__compile_slots = compile_slots
        self.__checksums = {}
        self.workers = {}
        self.sessions = {}

    def create_session(self, client_id):
        session = CompileSession(self.__pch_repository,
            self.__header_repository, self.__compiler_repository,
            self.__counter, self.__checksums, self.__compile_thread_pool,
            self.__misc_thread_pool, self.scheduler)
        session.id = client_id
        return session

    def attach_session(self, session):
        socket = create_socket(zmq_ctx, zmq.DEALER)
        return id

    def terminate(self, id):
        if id in self.workers:
            del self.workers[id]
        if id in self.sessions:
            del self.sessions[id]

    def run(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(logging.NullHandler())

        self.__compile_thread_pool = ThreadPoolExecutor(self.__compile_slots)
        self.__misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
        self.__header_repository = HeaderRepository()
        self.__pch_repository = PCHRepository()
        self.__compiler_repository = CompilerRepository()
        self.__counter = Counter()

        self.scheduler = sched.scheduler()

        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        class ProcessMsg:
            def __init__(self, session):
                self.session = session

            def __call__(self, msg):
                self.session.process_msg(msg)

        clients = create_socket(zmq_ctx, zmq.ROUTER)
        if self.__port == 0:
            self.__port = bind_to_random_port(clients)
            self.__address = "tcp://*:{}".format(self.__port)
        else:
            self.__address = "tcp://*:{}".format(self.__port)
            clients.bind(self.__address)

        sessions = create_socket(zmq_ctx, zmq.DEALER)
        sessions.bind('inproc://sessions_socket')

        poller = zmq.Poller()
        poller.register(clients, zmq.POLLIN)
        poller.register(sessions, zmq.POLLIN)

        scheduler = sched.scheduler()

        print("Running server on '{}'.".format(self.__address))
        print("Using {} job slots.".format(self.__compile_slots))

        beacon = Beacon(self.__compile_slots, self.__port)
        beacon.start(multicast_address='224.3.29.71', multicast_port=51134)

        try:
            while True:
                sys.stdout.write("Currently running {} tasks.\r".format(self.__counter.get()))

                # Run any scheduled tasks.
                self.scheduler.run(False)

                for sock, event in dict(poller.poll(1000)).items():
                    assert event == zmq.POLLIN
                    if sock is clients:
                        client_id, *msg = recv_multipart(clients)
                        if len(msg) == 1 and msg[0] == b'PING':
                            clients.send_multipart([client_id, b'PONG'])
                            continue
                        elif not client_id in self.workers:
                            session = self.create_session(client_id)

                            class Terminate:
                                def __init__(self, worker, client_id):
                                    self.client_id = client_id
                                    self.worker = worker

                                def __call__(self):
                                    self.worker.terminate(self.client_id)

                            session.terminate = Terminate(self, client_id)
                            self.sessions[client_id] = session
                            self.workers[client_id] = ProcessMsg(session)
                        self.workers.get(client_id)(msg)
                    else:
                        assert sock is sessions
                        clients.send_multipart(recv_multipart(sessions))
        finally:
            beacon.stop()

    def shutdown(self):
        self.__compile_thread_pool.shutdown()
        self.__misc_thread_pool.shutdown()
