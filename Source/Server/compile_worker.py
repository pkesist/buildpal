from Common import send_compressed_file, SimpleTimer
from Common import create_socket

from io import BytesIO
from multiprocessing import Process, cpu_count
from time import sleep, time
from socket import getfqdn
from struct import pack
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .header_repository import HeaderRepository

import subprocess

import os
import pickle
import psutil
import signal
import shutil
import sys
import tarfile
import tempfile
import zipfile
import zlib
import zmq

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

    def async(func):
        def wrapper(inst, runner, *args, **kwds):
            return runner.submit(func, inst, *args, **kwds)
        return wrapper

    def __init__(self, file_repository, header_repository, compiler_repository,
                 cpu_usage_hwm, task_counter, checksums, compile_thread_pool,
                 misc_thread_pool):
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

    def __del__(self):
        try:
            shutil.rmtree(self.include_path)
            os.rmdir(self.include_path)
        except Exception:
            pass

    def created(self):
        assert self.state == self.STATE_START
        accept_task = not self.cpu_usage_hwm or psutil.cpu_percent() < self.cpu_usage_hwm
        self.socket.send_pyobj('ACCEPT' if accept_task else 'REJECT')
        self.state = self.STATE_GET_TASK if accept_task else self.STATE_DONE
        return accept_task

    def run_compiler(self):
        try:
            compiler_prep = time()
            # Wait for include dir to be prepared.
            self.prepare_include_dirs.result()
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

            start = time()
            self.times['compiler_prep'] = start - compiler_prep
            command = (self.task['call'] + pch_switch +
                [noLink, output] +
                [compiler_info.include_option.make_value(incpath).make_str()
                    for incpath in self.include_dirs] +
                [self.source_file])
            retcode, stdout, stderr = self.compiler(command,
                self.include_path)
            done = time()
            self.times['compiler'] = done - start
            self.times['server_time'] = self.server_time_timer.get()
            del self.server_time_timer
        except Exception:
            self.socket.send_multipart([b'SERVER_FAILED', pickle.dumps(time())])
        else:
            self.socket.send_multipart([b'SERVER_DONE', pickle.dumps((retcode,
                stdout, stderr, self.times)), pickle.dumps(time())])
            if retcode == 0:
                with open(object_file_name, 'rb') as obj:
                    send_compressed_file(self.socket.send_multipart, obj, copy=False)
        finally:
            os.remove(object_file_name)
            self.session_done()

    async_run_compiler = async(run_compiler)


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
        self.task_counter.inc()
        if self.task['pch_file'] is None:
            if self.header_state == self.STATE_HEADERS_ARRIVED:
                self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                self.async_run_compiler(self.compile_thread_pool)
            else:
                self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        else:
            self.state = self.STATE_SH_CHECK_PCH_TAG

    def session_done(self):
        self.detach()
        self.terminate()
        self.task_counter.dec()

    def process_msg(self, msg):
        if self.state == self.STATE_GET_TASK:
            self.server_time_timer = SimpleTimer()
            self.waiting_for_header_list = SimpleTimer()
            assert len(msg) == 3 and msg[0] == b'SERVER_TASK'
            self.task = pickle.loads(msg[1])
            self.times['task_travel_time'] = time() - pickle.loads(msg[2])
            self.compiler_id = self.task['compiler_info'].id()
            has_compiler = self.compiler_repository.has_compiler(self.compiler_id)
            if has_compiler is None:
                # Never heard of it.
                self.socket.send(b'NEED_COMPILER')
                self.state = self.STATE_WAITING_FOR_COMPILER
                self.compiler_data = BytesIO()
            else:
                self.socket.send(b'READY')
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
                self.socket.send(b'YES')
                self.pch_desc = open(self.pch_file, 'wb')
                self.pch_decompressor = zlib.decompressobj()
                self.state = self.STATE_SH_GET_PCH_DATA
            else:
                self.socket.send(b'NO')
                if self.header_state == self.STATE_HEADERS_ARRIVED:
                    self.times['waiting_for_mgr_data'] = self.waiting_for_manager_data.get()
                    self.async_run_compiler(self.compile_thread_pool)
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
                    self.async_run_compiler(self.compile_thread_pool)
                else:
                    self.state = self.STATE_SH_WAIT_FOR_TASK_DATA
        else:
            raise Exception("Invalid state.")

    @async
    def send_missing_files(self, filelist):
        self.times['async_missing_files'] = self.send_missing_files_timer.get()
        del self.send_missing_files_timer
        missing_files_timer = SimpleTimer()
        missing_files, self.repo_transaction_id = self.header_repository.missing_files(getfqdn(), filelist)
        self.times['process_hdr_list'] = missing_files_timer.get()
        self.attached_socket.send_multipart([b'MISSING_FILES', pickle.dumps(missing_files)])
        self.header_state = self.STATE_WAITING_FOR_HEADERS

    @async
    def prepare_include_dirs(self, tar_data):
        self.times['async_prep_inc_dir'] = self.prepare_include_dirs_timer.get()
        del self.prepare_include_dirs_timer
        shared_prepare_dir_timer = SimpleTimer()
        self.include_dirs = self.header_repository.prepare_dir(getfqdn(), tar_data, self.repo_transaction_id, self.include_path)
        self.times['shared_prepare_dir'] = shared_prepare_dir_timer.get()
        del shared_prepare_dir_timer
        self.header_state = self.STATE_HEADERS_ARRIVED
        if self.state == self.STATE_SH_WAIT_FOR_TASK_DATA:
            self.times['waiting_for_mgr_data'] = 0
            self.async_run_compiler(self.compile_thread_pool)
        else:
            self.waiting_for_manager_data = SimpleTimer()

    def process_attached_msg(self, msg):
        if self.header_state == self.STATE_WAITING_FOR_HEADER_LIST:
            if hasattr(self, 'waiting_for_header_list'):
                self.times['wait_for_header_list'] = self.waiting_for_header_list.get()
                del self.waiting_for_header_list
            else:
                self.times['wait_for_header_list'] = 0
            self.wait_for_headers = SimpleTimer()
            if not msg[0] == b'TASK_FILE_LIST':
                print("TASK_FILE_LIST", msg)
            assert msg[0] == b'TASK_FILE_LIST'
            filelist = pickle.loads(msg[1])
            self.send_missing_files_timer = SimpleTimer()
            self.send_missing_files(self.misc_thread_pool, filelist)
        elif self.header_state == self.STATE_WAITING_FOR_HEADERS:
            self.times['wait_for_headers'] = self.wait_for_headers.get()
            del self.wait_for_headers
            assert msg[0] == b'TASK_FILES'
            tar_data = msg[1]
            self.times['wait_hdr_list_result'] = pickle.loads(msg[2])
            self.prepare_include_dirs_timer = SimpleTimer()
            self.prepare_include_dirs = self.prepare_include_dirs(self.misc_thread_pool, tar_data)

class CompileWorker(Process):
    def __init__(self, address, file_repository,compiler_repository,
        cpu_usage_hwm, task_counter):
        Process.__init__(self)
        self.__address = address
        self.__file_repository = file_repository
        self.__compiler_repository = compiler_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter
        self.__checksums = {}
        self.workers = {}
        self.sessions = {}
        self.counter = 0

    def create_session(self, zmq_ctx):
        session = CompileSession(self.__file_repository,
            self.__header_repository, self.__compiler_repository,
            self.__cpu_usage_hwm, self.__task_counter,
            self.__checksums, self.__compile_thread_pool,
            self.__misc_thread_pool)
        session.id = b'S' + pack('>I', self.counter)
        self.counter += 1
        socket = create_socket(zmq_ctx, zmq.DEALER)
        socket.setsockopt(zmq.IDENTITY, session.id)
        socket.connect('inproc://sessions_socket')
        session.socket = socket
        return session

    def attach_session(self, zmq_ctx, session):
        socket = create_socket(zmq_ctx, zmq.DEALER)
        session.attached_id = b'S' + pack('>I', self.counter)
        self.counter += 1
        socket.setsockopt(zmq.IDENTITY, session.attached_id)
        socket.connect('inproc://sessions_socket')
        session.attached_socket = socket
        return id

    def terminate(self, id):
        session = self.sessions[id]
        session.socket.send(b'UNREGISTER')
        session.socket.disconnect('inproc://sessions_socket')
        del session.socket
        del self.workers[id]
        del self.sessions[id]

    def detach(self, session):
        session.attached_socket.send(b'UNREGISTER')
        session.attached_socket.disconnect('inproc://sessions_socket')
        del session.attached_socket
        del session.attached_id

    def run(self):
        zmq_ctx = zmq.Context()

        self.__compile_thread_pool = ThreadPoolExecutor(max_workers=cpu_count() + 1)
        self.__misc_thread_pool = ThreadPoolExecutor(max_workers=2 * cpu_count())
        self.__header_repository = HeaderRepository()

        import signal
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

        class ProcessMsg:
            def __init__(self, session):
                self.session = session

            def __call__(self, msg):
                self.session.process_msg(msg[1:])

        class ProcessAttachedMsg:
            def __init__(self, session):
                self.session = session

            def __call__(self, msg):
                self.session.process_attached_msg(msg[1:])

        clients = create_socket(zmq_ctx, zmq.ROUTER)
        clients.bind(self.__address)

        sessions = create_socket(zmq_ctx, zmq.ROUTER)
        sessions.bind('inproc://sessions_socket')

        poller = zmq.Poller()
        poller.register(clients, zmq.POLLIN)
        poller.register(sessions, zmq.POLLIN)
        
        self.session_to_client = {}

        while True:
            for sock, event in dict(poller.poll(1000)).items():
                assert event == zmq.POLLIN
                if sock is clients:
                    msg = clients.recv_multipart()
                    client_id = msg[0]
                    if msg[1] == b'CREATE_SESSION':
                        session = self.create_session(zmq_ctx)
                        session.terminate = lambda id=client_id : self.terminate(id)
                        session.detach = lambda session=session : self.detach(session)
                        self.session_to_client[session.id] = client_id

                        self.sessions[client_id] = session
                        self.workers[client_id] = session.process_msg
                        # TODO: Remove this, not needed.
                        clients.send_multipart([client_id, b'SESSION_CREATED'])
                        session.created()
                    elif msg[1] == b'ATTACH_TO_SESSION':
                        session_id = msg[2]
                        attacher_id = msg[0]
                        session = self.sessions[session_id]
                        self.attach_session(zmq_ctx, session)
                        self.session_to_client[session.attached_id] = attacher_id
                        self.workers[attacher_id] = session.process_attached_msg
                        # TODO: Remove this, not needed.
                        clients.send_multipart([attacher_id, b'SESSION_ATTACHED'])
                    else:
                        worker = self.workers.get(client_id)
                        if worker:
                            worker(msg[1:])
                else:
                    assert sock is sessions
                    msg = sessions.recv_multipart()
                    if msg[1] == b'UNREGISTER':
                        del self.session_to_client[msg[0]]
                    else:
                        clients.send_multipart([self.session_to_client[msg[0]]] + msg[1:])
