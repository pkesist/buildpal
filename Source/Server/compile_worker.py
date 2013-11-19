from Common import send_compressed_file, SimpleTimer
from Common import create_socket, recv_multipart

from io import BytesIO
from multiprocessing import Process, cpu_count
from time import sleep, time
from socket import getfqdn
from struct import pack
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread

from .header_repository import HeaderRepository
from .file_repository import FileRepository
from .compiler_repository import CompilerRepository

import subprocess

import os
import pickle
import psutil
import signal
import shutil
import sched
import sys
import tarfile
import tempfile
import zipfile
import zlib
import zmq
import queue


zmq_ctx = zmq.Context()

class Counter:
    def __init__(self):
        self.__count = 0

    def inc(self): self.__count += 1
    def dec(self): self.__count -= 1
    def get(self): return self.__count

class CompileSession:
    STATE_START = 0
    STATE_GET_TASK = 1
    STATE_DONE = 2
    STATE_SH_WAIT_FOR_TASK_DATA = 3
    STATE_WAITING_FOR_COMPILER = 4
    STATE_SH_CHECK_PCH_TAG = 5
    STATE_SH_GET_PCH_DATA = 6

    STATE_WAITING_FOR_HEADER_LIST = 0
    STATE_WAITING_FOR_HEADERS = 1
    STATE_HEADERS_ARRIVED = 2

    def verify(future):
        # This will raise an exception if we have one.
        # Otherwise we don't get any feedback from the
        # worker thread.
        future.result()

    def async(func):
        def wrapper(inst, runner, *args, **kwds):
            future = runner.submit(func, inst, *args, **kwds)
            future.add_done_callback(CompileSession.verify)
            return future
        return wrapper

    def __init__(self, file_repository, header_repository, compiler_repository,
                 cpu_usage_hwm, task_counter, checksums, compile_thread_pool,
                 misc_thread_pool, scheduler):
        self.state = self.STATE_START
        self.header_state = self.STATE_WAITING_FOR_HEADER_LIST
        self.task_counter = task_counter
        self.compiler_repository = compiler_repository
        self.header_repository = header_repository
        self.file_repository = file_repository
        self.cpu_usage_hwm = cpu_usage_hwm
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

    def created(self):
        assert self.state == self.STATE_START
        accept_task = not self.cpu_usage_hwm or psutil.cpu_percent() < self.cpu_usage_hwm
        sender = self.Sender(self.id)
        sender.send_pyobj('ACCEPT' if accept_task else 'REJECT')
        sender.disconnect()
        self.state = self.STATE_GET_TASK if accept_task else self.STATE_DONE
        return accept_task

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
            self.socket.disconnect('inproc://sessions_socket')

    def run_compiler(self):
        self.cancel_autodestruct()
        self.compile_thread_pool.submit(self.async_run_compiler, time()).add_done_callback(CompileSession.verify)

    def async_run_compiler(self, start_time):
        self.times['async_compiler_delay'] = time() - start_time
        try:
            compiler_prep = time()
            self.source_file = os.path.join(self.include_path, self.task['source'])
            if self.task['pch_file'] is not None:
                while not self.file_repository.file_arrived(
                    *self.task['pch_file']):
                    # The PCH file is being downloaded by another session.
                    # This could be made prettier by introducing another state
                    # in this state machine. However, wake-up event for that
                    # state would require inter-session communication.
                    # Just not worth the additional complexity.
                    sleep(1)

            object_file_handle, object_file_name = tempfile.mkstemp(suffix='.obj')
            os.close(object_file_handle)

            compiler_info = self.task['compiler_info']
            noLink = compiler_info.compile_no_link_option.make_value().make_str()
            output = compiler_info.object_name_option.make_value(
                object_file_name).make_str()
            pch_switch = []
            if self.task['pch_file']:
                assert self.pch_file is not None
                assert os.path.exists(self.pch_file)
                pch_switch.append(
                    compiler_info.pch_file_option.make_value(self.pch_file).make_str())

            while not self.compiler_repository.has_compiler(self.compiler_id):
                # Compiler is being downloaded by another session.
                # Similar to the PCH hack above.
                sleep(1)

            include_dirs = self.include_dirs_future.result()

            start = time()
            self.times['compiler_prep'] = start - compiler_prep
            command = (self.task['call'] + pch_switch +
                [noLink, output] +
                [compiler_info.include_option.make_value(incpath).make_str()
                    for incpath in include_dirs] +
                [self.source_file])
            retcode, stdout, stderr = self.compiler(command,
                self.include_path)
            done = time()
            self.times['compiler'] = done - start
            self.times['server_time'] = self.server_time_timer.get()
            del self.server_time_timer
        except Exception:
            sender = self.Sender(self.id)
            sender.send_multipart([b'SERVER_FAILED'])
            sender.disconnect()
            raise
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
            self.task['compiler_info'].executable())
        def spawn_compiler(command, cwd):
            command[0] = self.compiler_exe
            with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        self.compiler = spawn_compiler
        if self.task['pch_file'] is None:
            if self.header_state == self.STATE_HEADERS_ARRIVED:
                self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                self.run_compiler()
            else:
                self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        else:
            self.state = self.STATE_SH_CHECK_PCH_TAG

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
                assert len(msg) == 2 and msg[0] == b'SERVER_TASK'
                self.task = pickle.loads(msg[1])
                self.compiler_id = self.task['compiler_info'].id()
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
            elif self.state == self.STATE_SH_CHECK_PCH_TAG:
                tag = msg[0]
                assert tag == b'NEED_PCH_FILE'
                self.pch_file, required = self.file_repository.register_file(
                    *self.task['pch_file'])
                if required:
                    sender.send(b'YES')
                    if not os.path.exists(os.path.dirname(self.pch_file)):
                        os.makedirs(os.path.dirname(self.pch_file), exist_ok=True)
                    handle = os.open(self.pch_file, os.O_CREAT | os.O_WRONLY | os.O_NOINHERIT)
                    self.pch_desc = os.fdopen(handle, 'wb')
                    self.pch_decompressor = zlib.decompressobj()
                    self.state = self.STATE_SH_GET_PCH_DATA
                else:
                    sender.send(b'NO')
                    if self.header_state == self.STATE_HEADERS_ARRIVED:
                        self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                        self.run_compiler()
                    else:
                        self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
            elif self.state == self.STATE_SH_GET_PCH_DATA:
                more, data = msg
                self.pch_desc.write(self.pch_decompressor.decompress(data))
                if more == b'\x00':
                    self.pch_desc.write(self.pch_decompressor.flush())
                    self.pch_desc.close()
                    del self.pch_desc
                    del self.pch_decompressor
                    self.file_repository.file_completed(*self.task['pch_file'])
                    if self.header_state == self.STATE_HEADERS_ARRIVED:
                        self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                        self.run_compiler()
                    else:
                        self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
            else:
                raise Exception("Invalid state.")
        finally:
            sender.disconnect()

    @async
    def send_missing_files(self, filelist, attacher_id):
        try:
            sender = self.Sender(attacher_id)
            missing_files_timer = SimpleTimer()
            missing_files, self.repo_transaction_id = self.header_repository.missing_files(getfqdn(), filelist)
            self.times['process_hdr_list'] = missing_files_timer.get()
            sender.send_multipart([b'MISSING_FILES', pickle.dumps(missing_files)])
        finally:
            sender.disconnect()

    @async
    def prepare_include_dirs(self, tar_data):
        shared_prepare_dir_timer = SimpleTimer()
        result = self.header_repository.prepare_dir(getfqdn(), tar_data, self.repo_transaction_id, self.include_path)
        self.times['shared_prepare_dir'] = shared_prepare_dir_timer.get()
        del shared_prepare_dir_timer
        return result

    def process_attached_msg(self, attacher_id, msg):
        self.prolong_lifetime()
        if self.header_state == self.STATE_WAITING_FOR_HEADER_LIST:
            if hasattr(self, 'waiting_for_header_list'):
                self.times['wait_for_header_list'] = self.waiting_for_header_list.get()
                del self.waiting_for_header_list
            else:
                self.times['wait_for_header_list'] = 0
            self.wait_for_headers = SimpleTimer()
            assert msg[0] == b'TASK_FILE_LIST'
            filelist = pickle.loads(msg[1])
            self.header_state = self.STATE_WAITING_FOR_HEADERS
            self.send_missing_files(self.misc_thread_pool, filelist, attacher_id)
        elif self.header_state == self.STATE_WAITING_FOR_HEADERS:
            self.times['wait_for_headers'] = self.wait_for_headers.get()
            del self.wait_for_headers
            assert msg[0] == b'TASK_FILES'
            tar_data = msg[1]
            self.times['wait_hdr_list_result'] = pickle.loads(msg[2])
            self.header_state = self.STATE_HEADERS_ARRIVED
            self.waiting_for_manager_data = SimpleTimer()
            self.include_dirs_future = self.prepare_include_dirs(self.misc_thread_pool, tar_data)
            if self.state == self.STATE_SH_WAIT_FOR_TASK_DATA:
                self.times['waiting_for_mgr_data'] = 0
                self.include_dirs_future.add_done_callback(lambda future : self.run_compiler())

class CompileWorker:
    def __init__(self, address, cpu_usage_hwm):
        self.__address = address
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__checksums = {}
        self.workers = {}
        self.sessions = {}

    def create_session(self, client_id):
        session = CompileSession(self.__file_repository,
            self.__header_repository, self.__compiler_repository,
            self.__cpu_usage_hwm, self.__counter,
            self.__checksums, self.__compile_thread_pool,
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
        self.__compile_thread_pool = ThreadPoolExecutor(cpu_count() + 1)
        self.__misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
        self.__header_repository = HeaderRepository()
        self.__file_repository = FileRepository()
        self.__compiler_repository = CompilerRepository()
        self.__counter = Counter()

        self.scheduler = sched.scheduler()

        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        class ProcessAttachedMsg:
            def __init__(self, session, id):
                self.session = session
                self.id = id

            def __call__(self, msg):
                self.session.process_attached_msg(self.id, msg)

        class ProcessMsg:
            def __init__(self, session):
                self.session = session

            def __call__(self, msg):
                self.session.process_msg(msg)

        clients = create_socket(zmq_ctx, zmq.ROUTER)
        clients.bind(self.__address)

        sessions = create_socket(zmq_ctx, zmq.DEALER)
        sessions.bind('inproc://sessions_socket')

        poller = zmq.Poller()
        poller.register(clients, zmq.POLLIN)
        poller.register(sessions, zmq.POLLIN)

        scheduler = sched.scheduler()

        while True:
            sys.stdout.write("Running {} tasks.\r".format(self.__counter.get()))

            # Run any scheduled tasks.
            self.scheduler.run(False)

            for sock, event in dict(poller.poll(1000)).items():
                assert event == zmq.POLLIN
                if sock is clients:
                    client_id, *msg = recv_multipart(clients)
                    if msg[0] == b'CREATE_SESSION':
                        session = self.create_session(client_id)
                        session.terminate = lambda client_id=client_id : self.terminate(client_id)
                        self.sessions[client_id] = session
                        self.workers[client_id] = ProcessMsg(session)
                        # TODO: Remove this, not needed.
                        clients.send_multipart([client_id, b'SESSION_CREATED'])
                        session.created()
                    elif msg[0] == b'ATTACH_TO_SESSION':
                        session_id = msg[1]
                        session = self.sessions.get(session_id)
                        if session:
                            self.workers[client_id] = ProcessAttachedMsg(session, client_id)
                            clients.send_multipart([client_id, b'SESSION_ATTACHED'])
                    else:
                        worker = self.workers.get(client_id)
                        if worker:
                            worker(msg)
                else:
                    assert sock is sessions
                    clients.send_multipart(recv_multipart(sessions))

