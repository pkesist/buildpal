from Compilers import MSVCWrapper, Category, BuildLocalCategory, CompilerOption, FreeOption
from Common import SimpleTimer, send_compressed_file

import os
import pickle
import zlib
import zmq

from subprocess import list2cmdline

class OptionValues:
    def __init__(self, values):
        self.__values = values

    def free_options(self):
        return (token for token in self.__values if type(token.option) == FreeOption)

    def filter_options(self, filter):
        if type(filter) == type and issubclass(filter, Category):
            return (token for token in self.__values
                if type(token.option) == CompilerOption and
                token.option.test_category(filter))
        elif isinstance(filter, CompilerOption):
            return (token for token in self.__values
                if token.option.name() == filter.name())
        elif isinstance(filter, str):
            return (token for token in self.__values
                if token.option.name() == filter)
        raise RuntimeError("Unknown option filter.")

    def all(self):
        return self.__values


class TaskCreator:
    def __init__(self, compiler_wrapper, executable, cwd, sysincludes, command,
                 client_conn, timer):
        self.__compiler = compiler_wrapper
        self.__executable = executable
        self.__sysincludes = sysincludes.split(';')
        self.__client_conn = client_conn
        with timer.timeit('parse_options'):
            self.__option_values = OptionValues(list(compiler_wrapper.parse_options(cwd, command[1:])))
        self.__cwd = cwd

    def executable(self):
        return self.__executable

    def option_values(self):
        return self.__option_values

    def input_files(self):
        return (input.make_str() for input in self.__option_values.free_options())

    def build_local(self):
        return bool(list(self.option_values().filter_options(BuildLocalCategory)))

    def create_tasks(self):
        # See if user specified an explicit name for the object file.
        output = list(self.option_values().filter_options(self.__compiler.object_name_option()))
        if output:
            output = output[-1].val
        sources = [input for input in self.input_files() if self.__compiler.requires_preprocessing(input)]
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__compiler.object_name_option.esc(), self.__compiler.object_name_option.name()))

        compile_call, builtin_macros = self.__compiler.create_call(self.executable(), self.option_values())

        includes = [os.path.join(self.__cwd, token.val) for token in self.option_values().filter_options(self.__compiler.include_option())]
        macros = [token.val for token in self.option_values().filter_options(self.__compiler.define_option())]

        pch_header = list(self.option_values().filter_options(self.__compiler.use_pch_option()))
        if pch_header:
            assert len(pch_header) == 1
            pch_header = pch_header[0].val
            pch_file = list(self.option_values().filter_options(self.__compiler.pch_file_option()))
            assert len(pch_file) <= 1
            if pch_file:
                pch_file = pch_file[0].val
            else:
                pch_file = os.path.splitext(pch_header)[0] + '.pch'
            pch_file = os.path.join(self.__cwd, pch_file)
            if not os.path.exists(pch_file):
                raise Exception("PCH file '{}' does not exist.".format(pch_file))
            pch_file = os.path.join(self.__cwd, pch_file)
            pch_file_stat = os.stat(pch_file)
            pch_file = (pch_file, pch_file_stat.st_size, pch_file_stat.st_mtime)
        else:
            pch_header = None
            pch_file = None

        class Task:
            pass

        def create_task(source):
            if os.path.isabs(source):
                source = os.path.relpath(source, self.__cwd)

            task = Task()
            task.__dict__.update(
            {
                'server_task_info' : {
                    'call' : compile_call,
                    'source' : source,
                    'pch_file' : pch_file,
                },
                'preprocess_task_info' : {
                    'cwd' : self.__cwd,
                    'source' : source,
                    'macros' : macros + builtin_macros,
                    'includes' : includes,
                    'sysincludes' : self.__sysincludes,
                    'pch_header' : pch_header
                },
                'output' : os.path.join(self.__cwd, output or os.path.splitext(source)[0] + '.obj'),
                'pch_file' : pch_file,
                'source' : source,
            })
            return task
        return [create_task(source) for source in sources]

    def should_invoke_linker(self):
        return self.__compiler.compile_no_link_option() not in [token.option for token in self.option_values()]

    def postprocess(self):
        if not self.should_invoke_linker():
            return False, None

        print("Linking...")
        objects = {}
        for task in self.tasks:
            objects[task.source] = task.output

        call = [self.executable()]
        call.extend(o.make_str() for o in
            self.option_values().filter_options(LinkingCategory))
        for input in self.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        return True, subprocess.call(call)

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_OK = 1
    STATE_WAIT_FOR_PCH_RESPONSE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 4
    STATE_RECEIVE_RESULT_FILE = 5
    STATE_POSTPROCESS = 6
    STATE_WAIT_FOR_SESSION_DONE = 7
    STATE_WAIT_FOR_SEND_TAR_DONE = 9999

    def __init__(self, compiler, executable, cwd, sysincludes, command, timer,
        client_conn, server_conn, preprocess_socket, node_info, compiler_info):

        self.timer = timer
        self.client_conn = client_conn
        self.server_conn = server_conn
        self.preprocess_socket = preprocess_socket
        self.node_info = node_info
        self.compiler_info = compiler_info
        self.executable = executable

        assert compiler == 'msvc'
        self.compiler = MSVCWrapper()

        self.create_tasks(self.compiler, cwd, sysincludes, command)

    def create_tasks(self, compiler_wrapper, cwd, sysincludes, command):
        ctx = TaskCreator(compiler_wrapper, self.executable, cwd, sysincludes,
                          command, self.client_conn, self.timer)
        if ctx.build_local():
            call = [ctx.executable()]
            call.extend(option.make_str() for option in ctx.option_values().all())
            self.client_conn.send([b'EXECUTE_AND_EXIT\x00' + list2cmdline(call).encode() + b'\x00\x01'])
        else:
            self.tasks = ctx.create_tasks()
            self.task_index = 0
            self.start_task()

    @property
    def task(self):
        return self.tasks[self.task_index]

    def next_task(self):
        if self.task_index >= len(self.tasks) - 1:
            return False
        self.task_index += 1
        return True

    def start_task(self):
        if self.executable in self.compiler_info:
            self.task.compiler_info = self.compiler_info[self.executable]
            self.task.server_task_info['compiler_info'] = self.task.compiler_info
            self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
            server_id = self.server_conn.getsockopt(zmq.IDENTITY)
            assert server_id
            self.average_timer = SimpleTimer()
            self.preprocess_socket.send_multipart([server_id,
                pickle.dumps(self.task.preprocess_task_info),
                pickle.dumps(self.node_info.index())], copy=False)
            with self.timer.timeit('send'):
                self.server_conn.send_pyobj(self.task.server_task_info)
            self.node_info.add_tasks_sent()
            self.state = self.STATE_WAIT_FOR_OK
        else:
            self.test_source = self.compiler.prepare_test_source(self.executable)
            self.client_conn.send([b'EXECUTE_GET_OUTPUT', list2cmdline(self.test_source.command()).encode()])
            self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    def got_data_from_client(self, msg):
        assert self.state in [self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT]
        del self.test_source
        retcode = int(msg[0])
        stdout = msg[1]
        stderr = msg[2]
        info = self.compiler.compiler_info(self.executable, stdout, stderr)
        self.compiler_info[self.executable] = info
        self.task.compiler_info = self.compiler_info[self.executable]
        self.task.server_task_info['compiler_info'] = self.task.compiler_info
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
        server_id = self.server_conn.getsockopt(zmq.IDENTITY)
        assert server_id
        self.average_timer = SimpleTimer()
        self.preprocess_socket.send_multipart([server_id,
            pickle.dumps(self.task.preprocess_task_info),
            pickle.dumps(self.node_info.index())], copy=False)
        with self.timer.timeit('send'):
            self.server_conn.send_pyobj(self.task.server_task_info)
        self.node_info.add_tasks_sent()
        self.state = self.STATE_WAIT_FOR_OK

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_OK:
            task_ok = msg[0]
            assert msg[0] == b'OK'
            if self.task.pch_file:
                self.server_conn.send(b'NEED_PCH_FILE')
                self.state = self.STATE_WAIT_FOR_PCH_RESPONSE
            else:
                self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_PCH_RESPONSE:
            response = msg[0]
            if response == b'YES':
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_multipart, pch_file, copy=False)
            else:
                assert response == b'NO'
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_time = self.average_timer.get()
            del self.average_timer
            self.timer.add_time('server_time', server_time)
            self.node_info.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.client_conn.send([b'EXIT', b'-1'])
                self.state = self.STATE_WAIT_FOR_SESSION_DONE
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, server_times = pickle.loads(msg[1])
                for name, duration in server_times.items():
                    self.timer.add_time("server." + name, duration)
                if self.retcode == 0:
                    self.output = open(self.task.output, "wb")
                    self.output_decompressor = zlib.decompressobj()
                    self.state = self.STATE_RECEIVE_RESULT_FILE
                    self.receive_result_time = SimpleTimer()
                else:
                    self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                    self.node_info.add_tasks_completed()
                    self.state = self.STATE_WAIT_FOR_SESSION_DONE

        elif self.state == self.STATE_RECEIVE_RESULT_FILE:
            more, data = msg
            self.output.write(self.output_decompressor.decompress(data))
            if more == b'\x00':
                self.output.write(self.output_decompressor.flush())
                del self.output_decompressor
                self.timer.add_time('receive_result', self.receive_result_time.get())
                del self.receive_result_time
                self.output.close()
                del self.output
                self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                self.node_info.add_tasks_completed()
                if not self.next_task():
                    self.state = self.STATE_WAIT_FOR_SESSION_DONE
                else:
                    self.start_task()
        elif self.state == self.STATE_WAIT_FOR_SESSION_DONE:
            assert msg[0] == b'SESSION_DESTROYED'
            return True
        return False
