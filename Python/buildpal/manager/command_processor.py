from .task import Task, PreprocessTask
from .gui_event import GUIEvent

from buildpal.common import ServerTask

import os
import struct
import logging
from socket import getfqdn

class ClientTaskCompiler:
    def __init__(self, client_conn):
        self.client_conn = client_conn
        self.tasks_waiting = []
        self._client_ready = False
        self.current_task = None

    def client_ready(self):
        if self.tasks_waiting:
            self.current_task = self.tasks_waiting.pop(0)
            self.compile_on_client(*self.current_task)
        else:
            self._client_ready = True

    def append_task(self, compiler, options, task):
        if self._client_ready:
            self._client_ready = False
            self.compile_on_client(compiler, options, task)
        else:
            self.tasks_waiting.append((compiler. options, task))

    def compile_on_client(self, compiler, options, task):
        self.current_task = task
        call = options.create_server_call()
        for include in options.include_dirs():
            call.append(compiler.set_include_option().format(include))
        for define in options.defines():
            call.append(compiler.set_define_option().format(define))
        if options.pch_file():
            call.append(compiler.set_pch_file_option().format(options.pch_file()))
            call.append(compiler.set_use_pch_option().format(options.pch_header()))
        call.append(compiler.set_object_name_option().format(task.output))
        call.append(task.source)
        self.client_conn.do_execute_get_output(call)

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

    hostname = getfqdn()

    def __init__(self, client_conn, executable, cwd, sysinclude_dirs, compiler,
            command, database_inserter, global_timer, update_ui):
        self.client_conn = client_conn
        self.compiler = compiler
        self.executable = executable
        self.compiler_info = None
        self.__sysinclude_dirs = [x for x in
            sysinclude_dirs.split(os.path.pathsep) if x]
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
        self.client_conn.do_execute_get_output(self.test_source.command())
        self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    def got_data_from_client(self, msg):
        def pack_retcode(retcode):
            return struct.pack('!I', retcode & 0xFFFFFFFF)

        if self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT:
            self.test_source.destroy()
            del self.test_source
            retcode = int(msg[0].tobytes())
            stdout = msg[1].tobytes()
            stderr = msg[2].tobytes()
            try:
                if retcode != 0:
                    self.client_conn.do_exit(retcode,
                        b"BuildPal - failed to run test compile.\r\n" + stdout,
                        stderr)
                    return
                self.compiler_info, self.tmp_compiler_files = \
                    self.compiler.get_compiler_info(self.executable, stdout,
                    stderr)
            except Exception:
                # Failed to identify compiler.
                self.client_conn.do_run_locally()
            else:
                self.client_conn.do_locate_files(self.tmp_compiler_files)
                self.state = self.STATE_WAIT_FOR_COMPILER_FILE_LIST
        elif self.state == self.STATE_WAIT_FOR_COMPILER_FILE_LIST:
            assert len(msg) == len(self.tmp_compiler_files)
            self.compiler_info.set_files(list(zip([m.tobytes() for m in msg],
                self.tmp_compiler_files)))
            self.state = self.STATE_READY
            self.got_compiler_info()
            self.__client_task_compiler.client_ready()
        else:
            assert self.state == self.STATE_READY
            self.__client_task_compiler.task_done(msg)

    def update_task_ui(self, task):
        for _, (duration_name, duration) in task.time_durations():
            self.__global_timer.add_time(duration_name, duration)
        self.__update_ui(GUIEvent.update_global_timers, self.__global_timer.as_dict())

    def build_local(self):
        return self.__options.should_build_locally()

    def process_create_pch(self):
        pch_cmd = self.__options.create_pch_cmd()
        if not pch_cmd:
            return False
        logging.debug("Running PCH create '{}' locally.".format(pch_cmd))
        self.client_conn.do_execute_and_exit(pch_cmd)
        return True

    def compile_on_client(self, task):
        self.__client_task_compiler.append_task(self.compiler, self.__options, task)

    def create_tasks(self, compiler_info):
        pch_file = None
        pch_header = None
        if not self.__options.avoid_pch():
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

        def create_task(source, decorator, targets):
            if not os.path.isabs(source):
                source = os.path.join(self.__cwd, source)
            return Task(
                ServerTask(
                    self.hostname,
                    compiler_info,
                    self.__options.create_server_call(),
                    pch_header=pch_header,
                    pch_file=pch_file,
                    include_dirs=[os.path.join(self.__cwd, rel_inc) for rel_inc in
                        self.__options.include_dirs()] + self.__sysinclude_dirs,
                    forced_includes=self.__options.forced_includes(),
                    src_decorator=decorator
                ),
                PreprocessTask(
                    source,
                    self.__options.implicit_macros() + self.__options.defines()
                        + compiler_info.macros,
                    [os.path.join(self.__cwd, rel_inc) for rel_inc in
                        self.__options.include_dirs()],
                    self.__sysinclude_dirs,
                    self.__options.forced_includes(),
                    pch_header
                ),
                self,
                os.path.join(self.__cwd, targets['object_file']),
                [os.path.join(self.__cwd, target) for target in targets['all']],
                pch_file,
                source,)
        self.tasks = set(create_task(source, decorator, target) for source,
            decorator, target in self.__options.files())
        if not self.tasks:
            # No idea what the user wanted.
            self.client_conn.do_run_locally()
            return []
        self.completed_tasks = {}
        self.tasks_with_sessions_done = set()
        return self.tasks

    def task_completed(self, task, result):
        assert task in self.tasks
        assert task not in self.completed_tasks
        self.update_task_ui(task)
        self.completed_tasks[task] = result
        if self.tasks == self.completed_tasks.keys():
            self.postprocess()

    def all_sessions_done(self, task):
        self.tasks_with_sessions_done.add(task)
        if self.tasks_with_sessions_done == self.tasks:
            self.__database_inserter.async_insert(self.get_info())

    def should_invoke_linker(self):
        return self.__options.should_invoke_linker()

    def postprocess(self):
        exit_error_code = 0
        stdout = b''
        stderr = b''
        for _, result in self.completed_tasks.items():
            retcode, tmp_stdout, tmp_stderr = result
            if retcode != 0:
                exit_error_code = retcode
            stdout += tmp_stdout
            stderr += tmp_stderr

        if exit_error_code:
            logging.debug("Exiting with error code {}".format(exit_error_code))
            self.client_conn.do_exit(exit_error_code, stdout, stderr)
            return

        if not self.should_invoke_linker():
            logging.debug("Exiting with success error code")
            self.client_conn.do_exit(0, stdout, stderr)
            return

        call = []
        input_to_output = dict((x[0], x[2]) for x in self.__options.files())
        for input, _ in self.__options.source_files():
            output = input_to_output.get(input)
            if output:
                call.append(output['object_file'])
            else:
                call.append(input)

        call.extend(self.__options.link_options())
        call.extend(self.__options.input_files())
        self.client_conn.do_execute_and_exit(call)

    def get_info(self):
        assert self.tasks_with_sessions_done == self.tasks
        return {
            'command' : ', '.join([x[0] for x in self.__options.source_files()]),
            'tasks' : [task.get_info() for task in self.tasks]
        }

