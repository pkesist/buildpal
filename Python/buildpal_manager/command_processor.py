from .compile_session import SessionResult
from .task import Task
from .gui_event import GUIEvent

from subprocess import list2cmdline

import os
from time import time

class ClientTaskCompiler:
    def __init__(self, client_conn):
        self.client_conn = client_conn
        self.tasks_waiting = []
        self._client_ready = False
        self.current_task = None

    def client_ready(self):
        if self.tasks_waiting:
            self.current_task = self.tasks_waiting.pop(0)
            self.compile_on_client(*current_task)
        else:
            self._client_ready = True

    def append_task(self, compiler, options, task):
        if self._client_ready:
            self._client_ready = False
            self.compile_on_client(compiler, options, task)
        else:
            self.tasks_waiting.append((compiler. options, taks))

    def compile_on_client(self, compiler, options, task):
        self.current_task = task
        call = options.create_server_call()
        for include in options.includes():
            call.append(compiler.set_include_option().format(include))
        for define in options.defines():
            call.append(compiler.set_define_option().format(define))
        if options.pch_file:
            call.append(compiler.set_pch_file_option().format(options.pch_file()))
        call.append(compiler.set_object_name_option().format(task.output))
        call.append(task.source)
        self.client_conn.send_msg([b'EXECUTE_GET_OUTPUT',
            list2cmdline(call).encode()])

    def task_done(self, msg):
        assert self.current_task
        retcode = int(msg[0].tobytes())
        stdout = msg[1].tobytes()
        stderr = msg[2].tobytes()
        self.current_task.task_completed(retcode, stdout, stderr)
        self.client_ready()

class CommandProcessor:
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 0
    STATE_WAIT_FOR_COMPILER_FILE_LIST = 1
    STATE_READY = 2

    def __init__(self, client_conn, executable, cwd, sysincludes, compiler,
            command, database_inserter, global_timer, update_ui):
        self.client_conn = client_conn
        self.compiler = compiler
        self.executable = executable
        self.compiler_info = None
        self.__sysincludes = sysincludes.split(os.path.pathsep)
        self.__cwd = cwd
        self.__command = command
        self.__options = compiler.parse_options(command)
        self.__global_timer = global_timer
        self.__update_ui = update_ui
        self.__database_inserter = database_inserter
        self.__client_task_compiler = ClientTaskCompiler(client_conn)

    def set_compiler_info(self, compiler_info):
        self.compiler_info = compiler_info
        self.state = self.STATE_READY
        self.__client_task_compiler.client_ready()

    def request_compiler_info(self, on_completion):
        self.got_compiler_info = on_completion
        self.test_source = self.compiler.prepare_test_source()
        self.client_conn.send_msg([b'EXECUTE_GET_OUTPUT',
            list2cmdline(self.test_source.command()).encode()])
        self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    def got_data_from_client(self, msg):
        if self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT:
            self.test_source.destroy()
            del self.test_source
            retcode = int(msg[0].tobytes())
            stdout = msg[1].tobytes()
            stderr = msg[2].tobytes()
            try:
                self.compiler_info, self.tmp_compiler_files = \
                    self.compiler.get_compiler_info(self.executable, stdout,
                    stderr)
            except Exception:
                # Failed to identify compiler.
                self.client_conn.send_msg([b'RUN_LOCALLY'])
            else:
                self.client_conn.send_msg([b'LOCATE_FILES'] + self.tmp_compiler_files)
                self.state = self.STATE_WAIT_FOR_COMPILER_FILE_LIST
        elif self.state == self.STATE_WAIT_FOR_COMPILER_FILE_LIST:
            assert len(msg) == len(self.tmp_compiler_files)
            self.compiler_info['files'] = list(zip([m.tobytes() for m in msg],
                self.tmp_compiler_files))
            self.state = self.STATE_READY
            self.got_compiler_info()
            self.__client_task_compiler.client_ready()
        else:
            assert self.state == self.STATE_READY
            self.__client_task_compiler.task_done(msg)

    def update_task_ui(self, task):
        for duration_name, duration in task.durations.items():
            self.__global_timer.add_time(duration_name, duration)
        self.__update_ui(GUIEvent.update_global_timers, self.__global_timer.as_dict())

    def build_local(self):
        return self.__options.should_build_locally()

    def compile_on_client(self, task):
        self.__client_task_compiler.append_task(self.compiler, self.__options, task)

    def create_tasks(self):
        pch_file = None
        pch_header = self.__options.pch_header()
        if pch_header:
            pch_file = self.__options.pch_file()
            if not pch_file:
                pch_file = os.path.splitext(pch_header)[0] + '.pch'
            pch_file = os.path.join(self.__cwd, pch_file)
            if not os.path.exists(pch_file):
                raise Exception("PCH file '{}' does not exist.".format(
                    pch_file))
            pch_file = os.path.join(self.__cwd, pch_file)
            pch_file_stat = os.stat(pch_file)
            pch_file = (pch_file, pch_file_stat.st_size, pch_file_stat.st_mtime)

        def create_task(source, target):
            if not os.path.isabs(source):
                source = os.path.join(self.__cwd, source)
            return Task(dict(
                server_task_info=dict(
                    call=self.__options.create_server_call(),
                    pch_file=pch_file,
                ),
                preprocess_task_info=dict(
                    source=source,
                    macros=self.__options.implicit_macros() + 
                        self.__options.defines(),
                    includes=[os.path.join(self.__cwd, rel_inc) for rel_inc in
                        self.__options.includes()],
                    sysincludes=self.__sysincludes,
                    pch_header=pch_header
                ),
                command_processor=self,
                client_conn=self.client_conn,
                output=os.path.join(self.__cwd, target),
                pch_file=pch_file,
                source=source,
            ))
        self.tasks = set(create_task(source, target) for source, target in
            self.__options.files())
        self.completed_tasks = set()
        return self.tasks

    def task_completed(self, task):
        assert task in self.tasks
        assert task not in self.completed_tasks
        assert task.task_result is not None
        self.update_task_ui(task)
        self.completed_tasks.add(task)
        if self.tasks == self.completed_tasks:
            self.__database_inserter.async_insert(self.get_info())
            self.postprocess()

    def should_invoke_linker(self):
        return self.__options.should_invoke_linker()

    def postprocess(self):
        error_code = None
        stdout = b''
        stderr = b''
        objects = {}
        for task in self.completed_tasks:
            retcode, tmp_stdout, tmp_stderr = task.task_result
            if retcode != 0:
                error_code = str(retcode).encode()
            else:
                if hasattr(task, 'output_file_future'):
                    objects[task.source] = task.output_file_future.result()
                else:
                    objects[task.source] = task.output
            stdout += tmp_stdout
            stderr += tmp_stderr

        if error_code:
            self.client_conn.send_msg([b'EXIT', error_code, stdout, stderr])
            self.client_conn.close()
            return

        if not self.should_invoke_linker():
            self.client_conn.send_msg([b'EXIT', b'0', stdout, stderr])
            self.client_conn.close()
            return

        call = []
        for input in self.__options.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)

        link_opts = self.__options.link_options()
        if link_opts:
            call.extend(*link_opts)

        self.client_conn.send_msg([b'EXECUTE_AND_EXIT', list2cmdline(call).encode()])
        self.client_conn.close()

    def get_info(self):
        assert self.tasks == self.completed_tasks
        return {
            'command' : ', '.join(self.__options.input_files()),
            'tasks' : [task.get_info() for task in self.tasks]
        }

