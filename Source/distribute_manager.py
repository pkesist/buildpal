#! python3.3
from functools import cmp_to_key
from queue import Empty
from multiprocessing import Lock, Process, Pool, Queue
from multiprocessing.connection import Connection, Client
from multiprocessing.managers import BaseManager, SyncManager, BaseProxy
from concurrent.futures import ThreadPoolExecutor
from threading import Lock as ThreadLock
from time import sleep, time

from scan_headers import rewrite_includes, collect_headers, create_pth
from utils import send_file, receive_compressed_file, send_compressed_file, relay_file

import configparser
import operator
import os
import socket
import sys
import zmq

from Messaging import Client as MsgClient

class ScopedTimer:
    def __init__(self, callable):
        self.__callable = callable
        self.__start = time()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__callable(time() - self.__start)

class Timer:
    def __init__(self):
        self.__times = {}

    def add_time(self, type, value):
        current = self.__times.get(type, (0, 0))
        self.__times[type] = (current[0] + value, current[1] + 1)

    def as_dict(self):
        return self.__times

class TimerProxy(BaseProxy):
    _exposed_ = ('add_time', 'as_dict', 'timeit')
    def add_time(self, type, value):
        return self._callmethod('add_time', (type, value))

    def as_dict(self):
        return self._callmethod('as_dict')

    def timeit(self, name):
        return ScopedTimer(lambda value : self.add_time(name, value))

def prepare_task(algorithm, cwd, source, preprocessor_info, pch_header, pth_file):
    # TODO: This does not belong here. Move this to msvc.py.
    # We would like to avoid scanning system headers here if possible.
    # If we do so, we lose any preprocessor side-effects. We try to
    # hardcode this knowledge here.
    macros = preprocessor_info.all_macros
    if '_DEBUG' in macros:
        if not any(('_SECURE_SCL' in x for x in macros)):
            macros.append('_SECURE_SCL=1')
        if not any(('_HAS_ITERATOR_DEBUGGING' in x for x in macros)):
            macros.append('_HAS_ITERATOR_DEBUGGING=1')

    if algorithm == 'SCAN_HEADERS':
        # Create/Use PTH if we have precompiled header.
        return collect_headers(os.path.join(cwd, source),
            preprocessor_info.includes, [], macros,
            pth_file if pth_file else "",
            [pch_header] if pch_header else [])

    elif algorithm == 'REWRITE_INCLUDES':
        return rewrite_includes(os.path.join(cwd, source),
            preprocessor_info.includes, preprocessor_info.sysincludes,
            macros, pth_file if pth_file else "")
    else:
        raise Exception("Invalid algorithm.")


class PTHFileRepository:
    def __init__(self):
        self.__lock = ThreadLock()
        self.__files = {}

    def acquire(self):
        self.__lock.acquire()

    def release(self):
        self.__lock.release()

    def registered(self, file, timestamp):
        return file in self.__files and self.__files[file] >= timestamp

    def register(self, file):
        self.__files[file] = os.stat(file).st_mtime

def get_node(zmq_ctx, nodes, node_info):
    def cmp(lhs, rhs):
        #lhs_tasks_processing = node_info.tasks_processing(lhs)
        #rhs_tasks_processing = node_info.tasks_processing(rhs)
        lhs_tasks_processing = node_info.connections(lhs)
        rhs_tasks_processing = node_info.connections(rhs)
        lhs_average_time = node_info.average_time(lhs)
        rhs_average_time = node_info.average_time(rhs)
        if lhs_average_time == 0 and rhs_average_time == 0:
            return -1 if lhs_tasks_processing < rhs_tasks_processing else 1
        if lhs_tasks_processing == 0 and rhs_tasks_processing == 0:
            return -1 if lhs_average_time < rhs_average_time else 1
        return -1 if lhs_tasks_processing * lhs_average_time <= rhs_tasks_processing * rhs_average_time else 1
        
    node_index = min(range(len(nodes)), key=cmp_to_key(cmp))
    node = nodes[node_index]
    try:
        client = MsgClient(zmq_ctx)
        client.connect('tcp://{}:{}'.format(node[0], node[1]))
    except Exception:
        print("Failed to connect to '{}'".format(node))
        print(node)
        import traceback
        traceback.print_exc()
        return None
    accept = client.recv_pyobj()
    if accept == "ACCEPT":
        return node_index, client
    else:
        assert accept == "REJECT"
        return None

def set_zmq_ctx():
    global zmq_ctx
    zmq_ctx = zmq.Context()

def get_zmq_ctx():
    global zmq_ctx
    return zmq_ctx

class CompileWorker:
    def __init__(self, task):
        self.task = task

    def __call__(self, client_id, timer, nodes, node_info, prepare_pool, pth_file_repository):
        try:
            client_conn = Client(address=r"\\.\pipe\{}".format(client_id), authkey=None)
            if self.task.pch_header:
                for include_path in self.task.preprocessor_info.includes:
                    pch_header = os.path.join(include_path, self.task.pch_header)
                    if os.path.exists(pch_header):
                        found = True
                        break
                assert found or not "Could not locate precompiled header '{}'".format(self.task.pch_header)
                pth_file = os.path.splitext(self.task.pch_file[0])[0] + '.clang.pth'
                pth_file_repository.acquire()
                try:
                    if not pth_file_repository.registered(pth_file, os.stat(pch_header).st_mtime):
                        with timer.timeit('create_pth'):
                            create_pth(self.task.pch_header,
                                pth_file,
                                self.task.preprocessor_info.includes,
                                self.task.preprocessor_info.sysincludes,
                                self.task.preprocessor_info.all_macros)
                            pth_file_repository.register(pth_file)
                finally:
                    pth_file_repository.release()
            else:
                pth_file = None

            with timer.timeit('prepare'):
                start = time()
                if self.task.algorithm in ['SCAN_HEADERS', 'REWRITE_INCLUDES']:
                    self.task.tempfile = prepare_pool.async_run(prepare_task, (
                        self.task.algorithm, self.task.cwd, self.task.source,
                        self.task.preprocessor_info, self.task.pch_header, pth_file))

            with timer.timeit('find_available_node'):
                get_result = None
                while True:
                    get_result = get_node(get_zmq_ctx(), nodes, node_info)
                    if get_result:
                        break
                    with timer.timeit('find_available_node.sleeping'):
                        sleep(1)
                node_index, server_conn = get_result

            try:
                node_info.connection_open(node_index)
                node_info.add_tasks_sent(node_index)
                with timer.timeit('send'):
                    server_conn.send_pyobj(self.task)
                task_ok = server_conn.recv_pyobj()
                assert task_ok == 'OK'
                self.__send(client_conn, server_conn, prepare_pool, timer)

                # Just block
                with timer.timeit('server_time'), ScopedTimer(lambda value : node_info.add_total_time(node_index, value)):
                    server_status = server_conn.recv_pyobj()
                    if server_status == "SERVER_FAILED":
                        return None

                assert server_status == "SERVER_DONE"
                with timer.timeit('receive'):
                    self.__recv(client_conn, server_conn, timer)
                    node_info.add_tasks_completed(node_index)
            except:
                import traceback
                traceback.print_exc()
            finally:
                node_info.connection_closed(node_index)
        except Exception:
            import traceback
            traceback.print_exc()

    def __send(self, client_conn, server_conn, prepare_pool, timer):
        if self.task.algorithm == 'SCAN_HEADERS':
            server_conn.send_pyobj('SCAN_HEADERS')
            server_conn.send_pyobj('ZIP_FILE')
            with timer.timeit('prepare_result'):
                tempfile = prepare_pool.get_result(self.task.tempfile)
            assert tempfile
            with timer.timeit('send.zip'), open(tempfile, 'rb') as file:
                send_file(server_conn.send_pyobj, file)
            server_conn.send_pyobj('SOURCE_FILE')
            with timer.timeit('send.source'), open(os.path.join(self.task.cwd, self.task.source), 'rb') as cpp:
                send_compressed_file(server_conn.send_pyobj, cpp)
            if self.task.pch_file:
                server_conn.send_pyobj('NEED_PCH_FILE')
                response = server_conn.recv_pyobj()
                if response == "YES":
                    with timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                        send_compressed_file(server_conn.send_pyobj, pch_file)
                else:
                    assert response == "NO"

        if self.task.algorithm == 'PREPROCESS_LOCALLY':
            server_conn.send('PREPROCESS_LOCALLY')
            # Signal the client to do preprocessing.
            client_conn.send('PREPROCESS')
            server_conn.send('PREPROCESSED_FILE')
            relay_file(client_conn.recv, server_conn.send_pyobj)

        if self.task.algorithm == 'REWRITE_INCLUDES':
            server_conn.send_pyobj('PREPROCESS_LOCALLY')
            with timer.timeit('prepare_result'):
                tempfile = prepare_pool.get_result(self.task.tempfile)
            server_conn.send_pyobj('PREPROCESSED_FILE')
            send_compressed_file(server_conn.send_pyobj, io.BytesIO(tempfile))

        if self.task.algorithm == 'PREPROCESS_LOCALLY_WITH_BUILTIN_PREPROCESSOR':
            server_conn.send_pyobj('PREPROCESS_LOCALLY')
            from scan_headers import preprocess_file
            macros = self.task.preprocessor_info.macros + self.task.preprocessor_info.builtin_macros
            preprocessed_data = preprocess_file(
                os.path.join(self.task.cwd, self.task.source),
                self.task.preprocessor_info.includes,
                self.task.preprocessor_info.sysincludes,
                macros, self.task.compiler_info)
            send_compressed_file(server_conn.send_pyobj, io.BytesIO(preprocessed_data))

    def __recv(self, client_conn, server_conn, timer):
        with timer.timeit("receive.server"):
            retcode, stdout, stderr = server_conn.recv_pyobj()
        if retcode == 0:
            length = 0
            more = True
            with timer.timeit("receive.object"), open(self.task.output, "wb") as file:
                receive_compressed_file(server_conn.recv_pyobj, file)
        with timer.timeit("receive.client"):
            client_conn.send('COMPLETED')
            client_conn.send((retcode, stdout, stderr))

class TaskProcessor(Process):
    def __init__(self, nodes, task_queue, max_processes):
        self.__task_queue = task_queue
        self.__nodes = nodes
        self.__max_processes = max_processes

        super(TaskProcessor, self).__init__()

    def run(self):
        with BookKeepingManager() as book_keeper, \
            BookKeepingManager() as preparer, \
            Pool(processes=self.__max_processes, initializer=set_zmq_ctx, initargs=()) as compile_pool:
            pth_files = book_keeper.PTHFileRepository()
            node_info = book_keeper.NodeInfoHolder(len(self.__nodes))
            timer = book_keeper.Timer()
            prepare_pool = preparer.ThreadPool(32)
            while True:
                self.print_stats(node_info, timer.as_dict())
                try:
                    task, client_id = self.__task_queue.get(timeout=2)
                    compile_pool.apply_async(CompileWorker(task), args=(client_id, timer, self.__nodes, node_info, prepare_pool, pth_files))
                except Empty:
                    pass

    def print_stats(self, node_info, times):
        sys.stdout.write("================\n")
        sys.stdout.write("Build nodes:\n")
        sys.stdout.write("================\n")
        for index in range(len(self.__nodes)):
            node = self.__nodes[index]
            sys.stdout.write('{:15}:{:5} - Tasks sent {:<3} '
                'Open Connections {:<3} Completed {:<3} Failed '
                '{:<3} Running {:<3} Average Time {:<3.2f} Ratio {:<3.2f}\n'.format(
                node[0],
                node[1],
                node_info.tasks_sent      (index),
                node_info.connections     (index),
                node_info.tasks_completed (index),
                node_info.tasks_failed    (index),
                node_info.tasks_processing(index),
                node_info.average_time    (index),
                node_info.completion_ratio(index)))
        sys.stdout.write("================\n")
        sys.stdout.write("\r" * (len(self.__nodes) + 4))
        sorted_times = [(name, total, count, total / count) for name, (total, count) in times.items()]
        sorted_times.sort(key=operator.itemgetter(3), reverse=True)
        for name, time, count, average in sorted_times:
            print('{:-<30} Total {:->10.2f} Num {:->5} Average {:->10.2f}'.format(name, time, count, average))

task_queue = Queue()

class NodeInfoHolder:
    class NodeInfo:
        def __init__(self):
            self._tasks_completed  = 0
            self._tasks_failed     = 0
            self._tasks_sent       = 0
            self._total_time       = 0
            self._open_connections = 0

    def __init__(self, size):
        self.__nodes = tuple((NodeInfoHolder.NodeInfo() for i in range(size)))

    def connection_open(self, index): self.__nodes[index]._open_connections += 1

    def connection_closed(self, index): self.__nodes[index]._open_connections -= 1

    def connections(self, index): return self.__nodes[index]._open_connections

    def tasks_sent(self, index): return self.__nodes[index]._tasks_sent

    def tasks_completed(self, index): return self.__nodes[index]._tasks_completed

    def tasks_failed(self, index): return self.__nodes[index]._tasks_failed

    def tasks_processing(self, index): return self.tasks_sent(index) - self.tasks_completed(index) - self.tasks_failed(index)

    def total_time(self, index): return self.__nodes[index]._total_time

    def average_time(self, index):
        tasks_completed = self.tasks_completed(index)
        return self.total_time(index) / tasks_completed if tasks_completed else 0

    def add_tasks_sent(self, index): self.__nodes[index]._tasks_sent += 1

    def dec_tasks_sent(self, index): self.__nodes[index]._tasks_sent -= 1

    def add_tasks_completed(self, index): self.__nodes[index]._tasks_completed += 1

    def add_tasks_failed(self, index): self.__nodes[index]._add_tasks_failed += 1

    def add_total_time(self, index, value): self.__nodes[index]._total_time += value

    def completion_ratio(self, index):
        if not self.tasks_sent(index):
            return 1.0
        return self.tasks_completed(index) / self.tasks_sent(index)

class ThreadPool:
    def __init__(self, workers):
        self.__executor = ThreadPoolExecutor(max_workers=workers)
        self.__async_tasks = {}
        self.__counter = 0

    def async_run(self, callable, args):
        id = self.__counter
        self.__counter += 1
        self.__async_tasks[id] = self.__executor.submit(callable, *args)
        return id

    def get_result(self, id):
        result = self.__async_tasks[id].result()
        del self.__async_tasks[id]
        return result

class BookKeepingManager(SyncManager):
    pass

BookKeepingManager.register('ThreadPool', ThreadPool)
BookKeepingManager.register('Timer', Timer, TimerProxy)
BookKeepingManager.register('NodeInfoHolder', NodeInfoHolder)
BookKeepingManager.register('PTHFileRepository', PTHFileRepository)

def queue_task(task, client_id):
    task_queue.put((task, client_id))

class QueueManager(BaseManager):
    pass

QueueManager.register('queue_task', callable=queue_task)

default_script = 'distribute_manager.ini'

if __name__ == "__main__":
    if len(sys.argv) == 2:
        iniFile = os.path.join(os.getcwd(), sys.argv[1])
    else:
        iniFile = os.path.join(os.getcwd(), default_script)
    if not os.path.isfile(iniFile):
        print("""
Usage:
    {} [<ini-file>]

    If no <ini-file> is specified, script will attept to use '{}'
    in the current directory.
""").format(sys.argv[0], default_script)
        raise SystemExit()

    config = configparser.SafeConfigParser(strict=False)
    if not config.read(iniFile):
        raise Exception("Error reading the configuration file "
            "'{}'.".format(iniFile))

    manager_section = 'Manager'
    nodes_section = 'Build Nodes'

    id = config.get(manager_section, 'id')
    max_processes = config.getint(manager_section, 'max_processes', fallback=None)

    if not nodes_section in config:
        raise "ERROR: No '{}' section in '{}'.".format(nodes_section, iniFile)

    nodes = []
    section = config[nodes_section]
    done = False
    while not done:
        option = "node[{}]".format(len(nodes))
        if option in section:
            value = section[option]
            delim = ':'
            if not delim in value:
                raise RuntimeError("Invalid node value. Node values should be given as <host>:<port>")
            index = value.index(delim)
            nodes.append((value[:index], int(value[index+1:])))
        else:
            done = True
    if not nodes:
        raise RuntimeErrors("No build nodes configured.")

    if max_processes is None:
        max_processes = 4 * len(nodes)
   
    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

    try:
        taskProcessor = TaskProcessor(nodes, task_queue, max_processes=max_processes)
        taskProcessor.start()
        queue_manager = QueueManager(r"\\.\pipe\{}".format(id), b"")
        server = queue_manager.get_server()
        server.serve_forever()
    finally:
        print("Shutting down.")
        taskProcessor.terminate()
