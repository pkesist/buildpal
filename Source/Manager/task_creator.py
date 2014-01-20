from subprocess import list2cmdline

import os

class TaskCreator:
    def __init__(self, executable, cwd, sysincludes, compiler, command):
        self.__executable = executable
        self.__sysincludes = sysincludes.split(';')
        self.__cwd = cwd
        self.__compiler = compiler
        self.__options = compiler.parse_options(command)

    def executable(self):
        return self.__executable

    def compiler(self):
        return self.__compiler

    def build_local(self):
        return self.__options.should_build_locally()

    def create_tasks(self, client_conn):
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

        class Task:
            def __init__(self, task_creator, client_conn):
                self.task_creator = task_creator
                self.client_conn = client_conn

            def compiler(self):
                return self.task_creator.compiler()

            def executable(self):
                return self.task_creator.executable()
                
            def completed(self, *args):
                self.task_creator.task_done(self, *args)

        def create_task(source, client_conn):
            if not os.path.isabs(source):
                source = os.path.join(self.__cwd, source)

            task = Task(self, client_conn)
            task.__dict__.update(
            {
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
                'output' : os.path.join(self.__cwd, output or os.path.splitext(source)[0] + '.obj'),
                'pch_file' : pch_file,
                'source' : source,
            })
            return task
        self.tasks = set(create_task(source, client_conn) for source in sources)
        self.completed_tasks = {}
        return self.tasks

    def task_done(self, task, retcode, stdout, stderr):
        assert task in self.tasks
        assert task not in self.completed_tasks
        self.completed_tasks[task] = (retcode, stdout, stderr)
        stdout = ''
        stderr = ''
        if self.tasks == self.completed_tasks.keys():
            self.postprocess(task.client_conn)

    def should_invoke_linker(self):
        return self.__options.should_invoke_linker()

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
            client_conn.send([b'EXIT', error_code, stdout, stderr])
            return

        if not self.should_invoke_linker():
            client_conn.send([b'EXIT', b'0', stdout, stderr])
            return

        objects = {}
        for task in self.tasks:
            objects[task.source] = task.output

        call = [self.executable()]

        for input in self.__options.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)

        link_opts = self.__options.link_options()
        if link_opts:
            call.extend(*link_opts)

        client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(call).encode()])


def create_tasks(client_conn, compiler, executable, cwd, sysincludes, command):
    task_creator = TaskCreator(executable, cwd, sysincludes, compiler, command)
    if task_creator.build_local():
        client_conn.send([b'EXECUTE_AND_EXIT', list2cmdline(['cl.exe'] + command).encode()])
        return []
    return task_creator.create_tasks(client_conn)
