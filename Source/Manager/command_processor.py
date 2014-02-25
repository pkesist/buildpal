from .compile_session import SessionResult
from .task import Task

from subprocess import list2cmdline

import os
from time import time

class CommandProcessor:
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 0
    STATE_WAIT_FOR_COMPILER_FILE_LIST = 1
    STATE_HAS_COMPILER_INFO = 2

    def __init__(self, client_conn, executable, cwd, sysincludes, compiler, command, ui_data):
        self.client_conn = client_conn
        self.__executable = executable
        self.__sysincludes = sysincludes.split(';')
        self.__cwd = cwd
        self.__compiler = compiler
        self.__command = command
        self.__options = compiler.parse_options(command)
        self.__ui_data = ui_data

    def set_compiler_info(self, compiler_info, compiler_files):
        self.compiler_info = compiler_info
        self.compiler_files = compiler_files
        self.state = self.STATE_HAS_COMPILER_INFO

    def request_compiler_info(self, on_completion):
        self.got_compiler_info = on_completion
        self.test_source = self.__compiler.prepare_test_source()
        self.client_conn.send([b'EXECUTE_GET_OUTPUT', list2cmdline(self.test_source.command()).encode()])
        self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    def got_data_from_client(self, msg):
        if self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT:
            self.test_source.destroy()
            del self.test_source
            retcode = int(msg[0])
            stdout = msg[1]
            stderr = msg[2]
            info, self.compiler_files = self.__compiler.compiler_info(
                self.__executable, stdout, stderr)
            self.compiler_info = info
            self.client_conn.send([b'LOCATE_FILES'] + self.compiler_files)
            self.state = self.STATE_WAIT_FOR_COMPILER_FILE_LIST
        elif self.state == self.STATE_WAIT_FOR_COMPILER_FILE_LIST:
            assert len(msg) == len(self.compiler_files)
            self.compiler_files = list(zip(msg, self.compiler_files))
            self.state = self.STATE_HAS_COMPILER_INFO
            self.got_compiler_info()
        else:
            assert not "Invalid state"

    def update_task_ui(self, task):
        for name, time in task.times.items():
            self.__ui_data.timer.add_time(name, time)

    def executable(self):
        return self.__executable

    def compiler(self):
        return self.__compiler

    def build_local(self):
        return self.__options.should_build_locally()

    def create_tasks(self):
        output = self.__options.output_file()
        sources = self.__options.input_files()
        if output and len(sources) > 1:
            raise RuntimeError("Cannot specify output file with multiple sources.")

        pch_file = None
        pch_header = self.__options.pch_header()
        if pch_header:
            pch_file = self.__options.pch_file()
            if not pch_file:
                pch_file = os.path.splitext(pch_header)[0] + '.pch'
            pch_file = os.path.join(self.__cwd, pch_file)
            if not os.path.exists(pch_file):
                raise Exception("PCH file '{}' does not exist.".format(pch_file))
            pch_file = os.path.join(self.__cwd, pch_file)
            pch_file_stat = os.stat(pch_file)
            pch_file = (pch_file, pch_file_stat.st_size, pch_file_stat.st_mtime)

        def create_task(source):
            if not os.path.isabs(source):
                source = os.path.join(self.__cwd, source)
            return Task({
                'server_task_info' : {
                    'call' : self.__options.create_server_call(),
                    'pch_file' : pch_file,
                },
                'preprocess_task_info' : {
                    'source' : source,
                    'macros' : self.__options.implicit_macros() + self.__options.defines(),
                    'includes' : [os.path.join(self.__cwd, rel_inc) for rel_inc in self.__options.includes()],
                    'sysincludes' : self.__sysincludes,
                    'pch_header' : pch_header
                },
                'compiler_files' : self.compiler_files,
                'command_processor' : self,
                'client_conn' : self.client_conn,
                'output' : os.path.join(self.__cwd, output or os.path.splitext(source)[0] + '.obj'),
                'pch_file' : pch_file,
                'source' : source,
            })
        self.tasks = set(create_task(source) for source in sources)
        self.completed_tasks = {}
        return self.tasks

    def task_completed(self, task, retcode, stdout, stderr):
        assert task in self.tasks
        assert task not in self.completed_tasks
        self.update_task_ui(task)
        self.completed_tasks[task] = (retcode, stdout, stderr)
        stdout = ''
        stderr = ''
        if self.tasks == self.completed_tasks.keys():
            self.__ui_data.command_info.append((", ".join(self.__options.input_files()), time(), self.tasks))
            self.postprocess()

    def should_invoke_linker(self):
        return self.__options.should_invoke_linker()

    def postprocess(self):
        error_code = None
        stdout = b''
        stderr = b''
        for task, result in self.completed_tasks.items():
            if result[0] != 0:
                error_code = str(result[0]).encode()
            stdout += result[1]
            stderr += result[2]
        if error_code:
            self.client_conn.send([b'EXIT', error_code, stdout, stderr])
            self.client_conn.close()
            return

        if not self.should_invoke_linker():
            self.client_conn.send([b'EXIT', b'0', stdout, stderr])
            self.client_conn.close()
            return

        objects = {}
        for task in self.tasks:
            objects[task.source] = task.output

        call = []
        for input in self.__options.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)

        link_opts = self.__options.link_options()
        if link_opts:
            call.extend(*link_opts)

        self.client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(call).encode()])
        self.client_conn.close()

    def get_info(self):
        assert self.tasks == self.completed_tasks.keys()
        return {
            'command' : self.__command,
            'tasks' : [task.get_info for task in self.tasks]
        }

