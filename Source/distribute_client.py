# call -----> analyze                                      -----> local_invocation
#                                                          -----> remote_invocation
#      -----> preprocess(local_invocation)                 -----> local_output
#      -----> remote_call(local_output, remote_invocation) -----> remote output
#      -----> postprocess call(remote_output)              -----> output

from cmdline_processing import FreeOption, CmdLineOption, CmdLineOptions
from distribute_task import CompileTask

import marshal
import os
import random
import subprocess
import sys
import zlib

from tempfile import mkstemp
from time import sleep
from multiprocessing.managers import BaseManager
from multiprocessing.connection import Client

class Distributer:
    def create_context(self, command):
        raise NotImplementedError("Distributer.create_context")

    def preprocess(self, context):
        raise NotImplementedError("Distributer.preprocess")

    def execute_remotely(self, context, remote_invocation):
        raise NotImplementedError("Distributer.execute_remotely")

    def postprocess(self, context):
        pass
    
    def execute(self, command):
        ctx = self.create_context(command)
        self.preprocess(ctx)
        self.execute_remotely(ctx)
        self.postprocess(ctx)


class CompilationDistributer(Distributer, CmdLineOptions):
    class Category: pass
    class PreprocessingCategory(Category): pass
    class CompilationCategory(Category): pass
    class LinkingCategory(Category): pass

    class CompilerOption(CmdLineOption):
        def __init__(self, name, esc, suff=None, has_arg=True, allow_spaces=True, allow_equal=True, default_separator=None):
            super().__init__(name, esc, suff, has_arg, allow_spaces, allow_equal, default_separator)
            self.__categories = set()

        def add_category(self, cat):
            self.__categories.add(cat)
        
        def test_category(self, cat):
            return cat in self.__categories

    class Context:
        def __init__(self, command, option_parser):
            self.__executable = command[1]
            self.__options = list(option_parser.parse_options(command[2:]))
            self.__manager_id = command[0]

            try:
                class TmpManager(BaseManager):
                    pass
                TmpManager.register('get_host')
                self.__manager = TmpManager(r"\\.\pipe\{}".format(self.__manager_id), b"")
                self.__manager.connect()
            except:
                raise EnvironmentError("Failed to connect to build manager "
                    "'{}'.".format(manager_id))

        def manager_id(self):
            return self.__manager_id

        def get_host(self):
            return self.__manager.get_host()._getvalue()

        def executable(self): return self.__executable

        def options(self): return self.__options

        def free_options(self):
            return (token for token in self.__options if type(token.option) == FreeOption)

        def filter_options(self, filter):
            if type(filter) == type and issubclass(filter, CompilationDistributer.Category):
                return (token for token in self.__options
                    if type(token.option) == CompilationDistributer.CompilerOption and
                    token.option.test_category(filter))
            if isinstance(filter, CompilationDistributer.CompilerOption):
                return (token for token in self.__options
                    if token.option == filter)
            raise RuntimeError("Unknown option filter.")
            

        def input_files(self):
            return (input.make_str() for input in self.free_options())
        
    def create_context(self, command):
        result = CompilationDistributer.Context(command, self)
        return result

    def __init__(self, preprocess_option, obj_name_option, compile_no_link_option):
        self.__preprocess = preprocess_option
        self.__name = obj_name_option
        self.__compile = compile_no_link_option
        self.__compile.add_category(CompilationDistributer.CompilationCategory)
        self.add_option(self.__compile)
        self.add_option(self.__name)

    def should_invoke_linker(self, ctx):
        return True

    def requires_preprocessing(self, file):
        return False

    def preprocess(self, ctx):
        tokens = list(ctx.filter_options(CompilationDistributer.PreprocessingCategory))
        tokens.append(CmdLineOption.Value(self.__preprocess, None, None, None, None))
        # See if user specified an explicit name for the object file.
        output = list(ctx.filter_options(self.__name))
        if output:
            output = output[-1].val
        else:
            output = None
        sources = [input for input in ctx.input_files() if self.requires_preprocessing(input)]
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__name.esc(), self.__name.name()))

        call = [ctx.executable()]
        call.extend(option.make_str() for option in tokens)

        class PreprocessingTask: pass
        ctx.tasks = []
        for source in sources:
            task = PreprocessingTask()
            task.source = source
            task.object = output or os.path.splitext(source)[0] + '.obj'
            task.type = os.path.splitext(source)[1]
            file, filename = mkstemp(text=True)
            local_call = call + [task.source]
            subprocess.check_call(local_call, stdout=file)
            os.close(file)
            task.preprocessed = filename
            ctx.tasks.append(task)

    def execute_remotely(self, ctx):
        tokens = list(ctx.filter_options(CompilationDistributer.CompilationCategory))
        call = [ctx.executable()]
        call += [option.make_str() for option in tokens]

        param = {'outputOption' : self.__name.make_value('{}').make_str(),
            'compileNoLink' : self.__compile.make_value().make_str()}

        for task in ctx.tasks:
            compile_task = CompileTask(call, task.preprocessed, task.type, task.object, param)
            accepted = False
            while not accepted:
                host = ctx.get_host()
                conn = Client(address=host)
                conn.send(compile_task)
                try:
                    accepted = conn.recv()
                    if not accepted:
                        print("Task rejected by '{}', trying next one".format(host))
                        conn.close()
                    else:
                        break
                except IOError:
                    pass
            print("Task sent to '{}:{}' via manager {}.".format(host[0], host[1], ctx.manager_id()))
            compile_task.accepted(conn)

    @classmethod
    def server_function(param, conn, cpu_usage, free_memory):
        import tempfile
        import zlib
        import os
        import subprocess


    def postprocess(self, ctx):
        if not self.should_invoke_linker(ctx):
            return

        print("Linking...")
        objects = {}
        for task in ctx.tasks:
            objects[task.source] = task.object

        call = [ctx.executable()]
        call.extend(o.make_str() for o in ctx.filter_options(CompilationDistributer.LinkingCategory))
        for input in ctx.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        retcode = subprocess.call(call)
        sys.exit(retcode)
