from Compilers import MSVCWrapper
from Common import SimpleTimer, MessageProtocol

from .source_scanner import SourceScanner
from .command_processor import CommandProcessor
from .database import Database, DatabaseInserter
from .timer import Timer
from .node_manager import NodeManager
from .console import ConsolePrinter
from .node_info import NodeInfo

import asyncio
import os
import sys

from multiprocessing import cpu_count
from subprocess import list2cmdline
from tempfile import mkstemp
from threading import Thread
from time import time

class ClientProcessor(MessageProtocol):
    def __init__(self, compiler_info, task_created_func, database_inserter,
            ui_data):
        MessageProtocol.__init__(self)
        self.compiler_info = compiler_info
        self.task_created_func = task_created_func
        self.ui_data = ui_data
        self.data = b''
        self.transport = None
        self.command_processor = None
        self.database_inserter = database_inserter

    def close(self):
        if self.transport:
            self.transport.close()

    def process_msg(self, msg):
        if self.command_processor is not None:
            self.command_processor.got_data_from_client(msg)
        else:
            self.__handle_new_client(msg)

    def __handle_new_client(self, msg):
        compiler_name = msg[0].decode()
        executable = msg[1].decode()
        sysincludes = msg[2].decode()
        cwd = msg[3].decode()
        command = [x.decode() for x in msg[4:]]
        assert compiler_name == 'msvc'
        compiler = MSVCWrapper()
        self.command_processor = CommandProcessor(self, executable, cwd,
            sysincludes, compiler, command, self.database_inserter,
            self.ui_data)

        if self.command_processor.build_local():
            self.send_msg([b'RUN_LOCALLY'])
            self.close()
            return True

        if executable in self.compiler_info:
            info, files = self.compiler_info[executable]
            self.command_processor.set_compiler_info(info, files)
            self.__create_tasks()
        else:
            self.command_processor.request_compiler_info(
                on_completion=self.__create_tasks)

    def __create_tasks(self):
        # No more data will be read from the client.
        assert self.command_processor.state == \
            self.command_processor.STATE_HAS_COMPILER_INFO
        if not self.command_processor.executable() in self.compiler_info:
            self.compiler_info[self.command_processor.executable()] = \
                self.command_processor.compiler_info, \
                self.command_processor.compiler_files
        for task in self.command_processor.create_tasks():
            task.server_task_info['compiler_info'] = task.compiler_info()
            task.preprocess_task_info['macros'].extend(
                task.compiler_info()['macros'])
            task.pp_timer = SimpleTimer()
            self.task_created_func(task)

class TaskProcessor:
    def __init__(self, nodes, port, n_pp_threads, ui_data):
        class CacheStats:
            def __init__(self):
                self.hits = 0
                self.misses = 0
                self.ratio = 0.0

            def update(self, data):
                self.hits, self.misses = data
                total = self.hits + self.misses
                if total == 0:
                    total = 1
                self.ratio = self.hits / total

        self.port = port
        self.compiler_info = {}
        self.timer = Timer()
        self.node_info = [NodeInfo(nodes[x]) for x in range(len(nodes))]
        self.server = None

        self.n_pp_threads = n_pp_threads
        if self.n_pp_threads <= 0:
            self.n_pp_threads = cpu_count()
        self.client_list = []

        self.loop = asyncio.ProactorEventLoop()
        self.node_manager = NodeManager(self.loop, self.node_info)
        self.source_scanner = SourceScanner(self.node_manager.task_ready,
            self.n_pp_threads)

        handle, db_file = mkstemp(prefix='buildpal_cmd', suffix='.db')
        os.close(handle)
        self.database = Database(db_file)
        with self.database.get_connection() as conn:
            self.database.create_structure(conn)

        self.ui_data = ui_data
        self.ui_data.timer = self.timer
        self.ui_data.node_info = self.node_info
        self.ui_data.command_info = []
        self.ui_data.command_db = self.database
        self.ui_data.cache_stats = self.source_scanner.get_cache_stats
        self.ui_data.unassigned_tasks = self.node_manager.unassigned_tasks_count

    def run(self, observer=None):
        if observer is None:
            observer = ConsolePrinter(self.node_info, self.ui_data)

        @asyncio.coroutine
        def observe():
            observer()
            yield from asyncio.sleep(0.5, loop=self.loop)
            asyncio.async(observe(), loop=self.loop)
        asyncio.async(observe(), loop=self.loop)

        database_inserter = DatabaseInserter(self.database)

        def client_processor_factory():
            return ClientProcessor(self.compiler_info, self.source_scanner.add_task,
                database_inserter, self.ui_data)

        [self.client_server] = self.loop.run_until_complete(
            self.loop.start_serving_pipe(
            client_processor_factory,
            "\\\\.\\pipe\\BuildPal_{}".format(self.port)))

        try:
            self.loop.run_forever()
        finally:
            database_inserter.close()
            self.source_scanner.close()
            self.loop.close()
            del self.loop

    def stop(self):
        def close_stuff():
            self.client_server.close()
            # If we do self.loop.stop() directly we (later on) get an exception
            # that task/future was never retrieved. Adding stop() to task queue
            # somehow avoids the issue. Reported to python.tulip mailing list.
            @asyncio.coroutine
            def stop_loop():
                self.loop.stop()
            asyncio.async(stop_loop(), loop=self.loop)
        self.loop.call_soon_threadsafe(close_stuff)
