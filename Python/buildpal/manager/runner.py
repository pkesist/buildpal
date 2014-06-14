from buildpal.common import SimpleTimer, MessageProtocol

from .source_scanner import SourceScanner
from .command_processor import CommandProcessor
from .database import Database, DatabaseInserter
from .timer import Timer
from .node_manager import NodeManager
from .console import ConsolePrinter
from .gui_event import GUIEvent

from struct import pack as struct_pack

import asyncio
import os
import sys

from multiprocessing import cpu_count
from subprocess import list2cmdline
from tempfile import mkstemp
from threading import Thread
from time import time

class ClientProcessor(MessageProtocol):
    def __init__(self, compiler_info_cache, task_created_func, database_inserter,
            global_timer, update_ui):
        MessageProtocol.__init__(self)
        self.compiler_info_cache = compiler_info_cache
        self.task_created_func = task_created_func
        self.global_timer = global_timer
        self.update_ui = update_ui
        self.data = b''
        self.transport = None
        self.command_processor = None
        self.database_inserter = database_inserter

    def do_exit(self, retcode, stdout, stderr):
        self.send_msg([b'EXIT', struct_pack('!I', retcode & 0xFFFFFFFF), stdout,
            stderr])
        self.close()

    def do_run_locally(self):
        self.send_msg([b'RUN_LOCALLY'])
        self.close()

    def do_execute_and_exit(self, cmd):
        self.send_msg([b'EXECUTE_AND_EXIT', list2cmdline(cmd).encode()])
        self.close()

    def do_locate_files(self, files):
        self.send_msg([b'LOCATE_FILES'] + files)

    def do_execute_get_output(self, cmd):    
        self.send_msg([b'EXECUTE_GET_OUTPUT', list2cmdline(cmd).encode()])

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
        from .compilers import MSVCCompiler
        compiler = MSVCCompiler()
        self.command_processor = CommandProcessor(self, executable, cwd,
            sysincludes, compiler, command, self.database_inserter,
            self.global_timer, self.update_ui)

        if self.command_processor.build_local():
            self.do_run_locally()
            return True

        if self.command_processor.process_create_pch():
            return True

        if executable in self.compiler_info_cache:
            self.command_processor.set_compiler_info(
                self.compiler_info_cache[executable])
            self.__create_tasks()
        else:
            self.command_processor.request_compiler_info(
                on_completion=self.__create_tasks)

    def __create_tasks(self):
        # No more data will be read from the client.
        assert self.command_processor.state == \
            self.command_processor.STATE_READY
        if not self.command_processor.executable in self.compiler_info_cache:
            self.compiler_info_cache[self.command_processor.executable] = \
                self.command_processor.compiler_info
        for task in self.command_processor.create_tasks(
                self.command_processor.compiler_info):
            self.task_created_func(task)

class ManagerRunner:
    def __init__(self, port, n_pp_threads):
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
        self.compiler_info_cache = {}
        self.timer = Timer()
        self.server = None

        self.n_pp_threads = n_pp_threads
        if self.n_pp_threads <= 0:
            self.n_pp_threads = cpu_count()

    def run(self, node_info_getter, update_ui=None, silent=False):
        if update_ui is None:
            self.update_ui = lambda event_type, event_data : None
        else:
            self.update_ui = update_ui

        handle, db_file = mkstemp(prefix='buildpal_cmd', suffix='.db')
        os.close(handle)
        self.database = Database(db_file)
        with self.database.get_connection() as conn:
            self.database.create_structure(conn)

        self.loop = asyncio.ProactorEventLoop()

        node_manager = NodeManager(self.loop, node_info_getter, self.update_ui)

        if update_ui is None and not silent:
            class UIData: pass
            ui_data = UIData()
            ui_data.timer = self.timer
            ui_data.command_db = self.database
            ui_data.cache_stats = lambda : source_scanner.get_cache_stats()
            observer = ConsolePrinter(node_manager.get_node_info, ui_data)
            @asyncio.coroutine
            def observe():
                observer()
                yield from asyncio.sleep(0.5, loop=self.loop)
                asyncio.async(observe(), loop=self.loop)
            asyncio.async(observe(), loop=self.loop)

        with DatabaseInserter(self.database, self.update_ui) as database_inserter, \
            SourceScanner(node_manager.task_preprocessed, self.update_ui,
                self.n_pp_threads) as source_scanner:

            def client_processor_factory():
                return ClientProcessor(self.compiler_info_cache, source_scanner.add_task,
                    database_inserter, self.timer, self.update_ui)

            [self.client_server] = self.loop.run_until_complete(
                self.loop.start_serving_pipe(
                client_processor_factory,
                "\\\\.\\pipe\\BuildPal_{}".format(self.port)))

            try:
                self.loop.run_forever()
            finally:
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
