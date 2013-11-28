from Compilers import Category, BuildLocalCategory, LinkingCategory, CompilerOption, FreeOption
from subprocess import list2cmdline

import os

class OptionValues:
    def __init__(self, values):
        self.__values = values

    def free_options(self):
        return (token for token in self.__values if type(token.option) == FreeOption)

    def filter_options(self, filter):
        if type(filter) == type and issubclass(filter, Category):
            return (token for token in self.__values
                if issubclass(type(token.option), CompilerOption) and
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
    def __init__(self, compiler_wrapper, executable, cwd, sysincludes, command):
        self.__compiler = compiler_wrapper
        self.__executable = executable
        self.__sysincludes = sysincludes.split(';')
        self.__option_values = OptionValues(list(compiler_wrapper.parse_options(cwd, command)))
        self.__cwd = cwd

    def executable(self):
        return self.__executable

    def option_values(self):
        return self.__option_values

    def input_files(self):
        result = []
        for input in self.__option_values.free_options():
            list = input.make_args()
            assert len(list) == 1
            result.append(list[0])
        return result

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

        compile_call, builtin_macros = self.__compiler.create_call(self.option_values())

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
            if not os.path.isabs(source):
                source = os.path.join(self.__cwd, source)

            task = Task()
            task.__dict__.update(
            {
                'server_task_info' : {
                    'call' : compile_call,
                    'pch_file' : pch_file,
                },
                'preprocess_task_info' : {
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
            task.task_done = lambda *args : self.task_done(task, *args)
            return task
        self.tasks = set(create_task(source) for source in sources)
        self.completed_tasks = {}
        return self.tasks

    def task_done(self, task, client_conn, retcode, stdout, stderr):
        assert task in self.tasks
        assert task not in self.completed_tasks
        self.completed_tasks[task] = (retcode, stdout, stderr)
        stdout = ''
        stderr = ''
        if self.tasks == self.completed_tasks.keys():
            self.postprocess(client_conn)

    def should_invoke_linker(self):
        return self.__compiler.compile_no_link_option() not in [
            token.option for token in self.option_values().all()]

    def postprocess(self, client_conn):
        error_code = None
        stdout = b''
        stderr = b''
        for task, result in self.completed_tasks.items():
            if result[0] != 0:
                error_code = str(result[0]).encode()
            stdout += result[1]
            stderr += result[2]
        if error_code:
            client_conn.send([b'COMPLETED', error_code, stdout, stderr])
            return

        if not self.should_invoke_linker():
            client_conn.send([b'COMPLETED', b'0', stdout, stderr])
            return

        objects = {}
        for task in self.tasks:
            objects[task.source] = task.output

        call = [self.executable()]

        for input in self.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)

        # Link options must go last.
        for o in self.option_values().filter_options(LinkingCategory):
            call.extend(o.make_args())

        client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(call).encode()])


def create_tasks(client_conn, compiler, executable, cwd, sysincludes, command):
    task_creator = TaskCreator(compiler, executable, cwd, sysincludes,
                        command)
    if task_creator.build_local():
        call = [task_creator.executable()]
        for option in task_creator.option_values().all():
            call.extend(option.make_args())
        client_conn.send([b'EXECUTE_AND_EXIT\x00' + list2cmdline(call).encode() + b'\x00\x01'])
        return []
    return task_creator.create_tasks()
