#! python3.3
from cmdline_processing import FreeOption, CmdLineOption, CmdLineOptions
from distribute_task import CompileTask

import os
import random
import subprocess
import string
import sys
import zlib
import zmq

from utils import send_compressed_file

class CompilerInfo:
    def __init__(self, toolset, executable, size, id, macros):
        self.__toolset = toolset
        self.__executable = executable
        self.__size = size
        self.__id = id
        self.__macros = macros

    def toolset(self): return self.__toolset
    def executable(self): return self.__executable
    def size(self): return self.__size
    def id(self): return self.__id
    def macros(self): return self.__macros

class PreprocessorInfo:
    def __init__(self, macros, builtin_macros, includes, sysincludes):
        self.macros = macros
        self.includes = includes
        self.sysincludes = sysincludes
        self.builtin_macros = builtin_macros

    @property
    def all_macros(self):
        return self.macros + self.builtin_macros

class CompilerWrapper(CmdLineOptions):
    class Category: pass
    class BuildLocalCategory(Category): pass
    class PCHCategory(Category): pass
    class PreprocessingCategory(Category): pass
    class CompilationCategory(Category): pass
    class LinkingCategory(Category): pass

    class CompilerOption(CmdLineOption):
        def __init__(self, name, esc, suff=None, has_arg=True, allow_spaces=True, allow_equal=True, default_separator=None):
            super().__init__(name, esc, suff, has_arg, allow_spaces, allow_equal, default_separator)
            self.__categories = set()
            self.__macros = set()

        def add_category(self, cat):
            self.__categories.add(cat)
        
        def test_category(self, cat):
            return cat in self.__categories

        def add_macro(self, macro):
            self.__macros.add(macro)

        def get_macros(self, value):
            result = []
            for macro in self.__macros:
                if callable(macro):
                    t = macro(value)
                    if t:
                        result.append(t)
                else:
                    result.append(macro)
            return result

    class Context:
        def __init__(self, command, option_parser, zmq_ctx):
            self.__options = list(option_parser.parse_options(command[1:]))
            self.__zmq_ctx = zmq_ctx
            self.__address = "tcp://localhost:{}".format(command[0])

        def connection(self):
            socket = self.__zmq_ctx.socket(zmq.DEALER)
            socket.connect(self.__address)
            return socket

        def zmq_ctx(self):
            return self.__zmq_ctx

        def executable(self):
            if not self.__executable:
                raise Exception("Internal error, compiler executable not set.")
            return self.__executable

        def set_executable(self, value):
            self.__executable = value

        def options(self): return self.__options

        def free_options(self):
            return (token for token in self.__options if type(token.option) == FreeOption)

        def filter_options(self, filter):
            if type(filter) == type and issubclass(filter, CompilerWrapper.Category):
                return (token for token in self.__options
                    if type(token.option) == CompilerWrapper.CompilerOption and
                    token.option.test_category(filter))
            if isinstance(filter, CompilerWrapper.CompilerOption):
                return (token for token in self.__options
                    if token.option.name() == filter.name())
            raise RuntimeError("Unknown option filter.")

        def input_files(self):
            return (input.make_str() for input in self.free_options())
        
    def create_context(self, command):
        return CompilerWrapper.Context(command, self, zmq.Context())

    def __run_locally(self, ctx):
        call = [ctx.executable()]
        call.extend(option.make_str() for option in ctx.options())
        return subprocess.call(call)

    def build_local(self, ctx):
        tokens = list(ctx.filter_options(CompilerWrapper.BuildLocalCategory))
        if not tokens:
            return False

        print("Command requires local compilation.")
        return True

    def execute(self, command, force_local=False):
        ctx = self.create_context(command)
        if self.build_local(ctx) or force_local:
            return self.__run_locally(ctx)
        self.create_tasks(ctx)
        retcode = self.execute_remotely(ctx)
        if retcode != 0:
            return retcode
        postprocessed, result = self.postprocess(ctx)
        if postprocessed:
            return result
        return retcode


    def compiler_info(self, executable):
        raise NotImplementedError("Compiler identification not implemented.")

    def preprocess_option(self): raise NotImplementedError()
    def object_name_option(self): raise NotImplementedError()
    def compile_no_link_option(self): raise NotImplementedError()
    def use_pch_option(self): raise NotImplementedError()
    def pch_file_option(self): raise NotImplementedError()

    def compiler_option_macros(self, tokens):
        result = []
        for token in (token for token in tokens
            if type(token.option) == CompilerWrapper.CompilerOption and
            token.option.test_category(CompilerWrapper.PreprocessingCategory)):
            option = token.option
            if not option:
                continue
            result += token.option.get_macros(token.val)
        return result

    def __init__(self):
        self.use_pch_option().add_category(CompilerWrapper.CompilationCategory)
        self.pch_file_option().add_category(CompilerWrapper.PCHCategory)
        self.compile_no_link_option().add_category(CompilerWrapper.CompilationCategory)
        self.include_file_option().add_category(CompilerWrapper.PreprocessingCategory)
        self.define_option().add_category(CompilerWrapper.PreprocessingCategory)
        self.add_option(self.compile_no_link_option())
        self.add_option(self.object_name_option())
        self.add_option(self.use_pch_option())
        self.add_option(self.pch_file_option())

    def should_invoke_linker(self, ctx):
        return self.compile_no_link_option() not in [token.option for token in ctx.options()]

    def requires_preprocessing(self, file):
        return False

    def compile_cpp(self, manager, source, obj, includes, locally=False):
        raise NotImplementedError()

    def create_tasks(self, ctx):
        # See if user specified an explicit name for the object file.
        output = list(ctx.filter_options(self.object_name_option()))
        if output:
            output = output[-1].val
        sources = [input for input in ctx.input_files() if self.requires_preprocessing(input)]
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.object_name_option.esc(), self.object_name_option.name()))

        preprocess_call = [ctx.executable()]
        preprocess_call.extend(option.make_str() for option in 
            ctx.filter_options(CompilerWrapper.PreprocessingCategory))
        preprocess_call.append(self.preprocess_option().make_value().make_str())

        compile_call = [ctx.executable()]
        compile_call.extend(option.make_str() for option in
            ctx.filter_options(CompilerWrapper.CompilationCategory))

        includes = [os.path.join(os.getcwd(), token.val) for token in ctx.filter_options(self.include_file_option())]
        macros = [token.val for token in ctx.filter_options(self.define_option())]
        sysincludes = os.getenv('INCLUDE', '').split(';')

        compiler_info = self.compiler_info(ctx.executable())
        builtin_macros = compiler_info.macros() + self.compiler_option_macros(ctx.options())

        pch_header = list(ctx.filter_options(self.use_pch_option()))
        if pch_header:
            assert len(pch_header) == 1
            pch_header = pch_header[0].val
            pch_file = list(ctx.filter_options(self.pch_file_option()))
            assert len(pch_file) <= 1
            if pch_file:
                pch_file = pch_file[0].val
            else:
                pch_file = os.path.splitext(pch_header)[0] + '.pch'
            if not os.path.exists(pch_file):
                raise Exception("PCH file '{}' does not exist.".format(pch_file))
            pch_file = os.path.join(os.getcwd(), pch_file)
            pch_file_stat = os.stat(pch_file)
            pch_file = (pch_file, pch_file_stat.st_size, pch_file_stat.st_mtime)
        else:
            pch_header = None
            pch_file = None

        def create_task(source):
            return CompileTask(
                call = compile_call,
                cwd = os.getcwd(),
                source = source,
                source_type = os.path.splitext(source)[1],
                preprocessor_info = PreprocessorInfo(macros, builtin_macros, includes, sysincludes),
                output = os.path.join(os.getcwd(), output or os.path.splitext(source)[0] + '.obj'),
                compiler_info = compiler_info,
                pch_file = pch_file,
                pch_header = pch_header,
                compilerWrapper = self)

        ctx.tasks = [(preprocess_call + [source], create_task(source)) for source in sources]

    def execute_remotely(self, ctx):
        zmq_ctx = ctx.zmq_ctx()
        for preprocess_call, compile_task in ctx.tasks:
            conn = ctx.connection()
            conn.send_pyobj(compile_task)
            response = conn.recv_pyobj()
            assert response == "TASK_RECEIVED"

            while True:
                request = conn.recv_pyobj()
                if request == 'PREPROCESS':
                    p = subprocess.Popen(preprocess_call, stdout=subprocess.PIPE)
                    send_compressed_file(conn.send_pyobj, p.stdout)
                elif request == 'COMPLETED':
                    retcode, stdout, stderr = conn.recv_pyobj()
                    sys.stdout.write(stdout.decode())
                    if stderr:
                        sys.stderr.write("---------------------------- STDERR ----------------------------\n")
                        sys.stderr.write(stderr.decode())
                        sys.stderr.write("----------------------------------------------------------------\n")
                    return retcode
                elif request == "FAILED":
                    return -1
                else:
                    print("GOT {}".format(request))
                    return -1
                

    def postprocess(self, ctx):
        if not self.should_invoke_linker(ctx):
            return False, None

        print("Linking...")
        objects = {}
        for preprocess_call, task in ctx.tasks:
            objects[task.source] = task.output

        call = [ctx.executable()]
        call.extend(o.make_str() for o in
            ctx.filter_options(CompilerWrapper.LinkingCategory))
        for input in ctx.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        return True, subprocess.call(call)
