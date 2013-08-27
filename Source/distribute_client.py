#! python3.3
from cmdline_processing import *
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
    def preprocess_option(self): raise NotImplementedError()
    def object_name_option(self): raise NotImplementedError()
    def compile_no_link_option(self): raise NotImplementedError()
    def define_option(self): raise NotImplementedError()
    def include_option(self): raise NotImplementedError()
    def use_pch_option(self): raise NotImplementedError()
    def pch_file_option(self): raise NotImplementedError()

    def __init__(self):
        self.use_pch_option().add_category(CompilationCategory)
        self.pch_file_option().add_category(PCHCategory)
        self.compile_no_link_option().add_category(CompilationCategory)
        self.include_option().add_category(PreprocessingCategory)
        self.define_option().add_category(PreprocessingCategory)
        self.add_option(self.compile_no_link_option())
        self.add_option(self.object_name_option())
        self.add_option(self.use_pch_option())
        self.add_option(self.pch_file_option())

    def compiler_info(self, executable):
        raise NotImplementedError("Compiler identification not implemented.")

    def compiler_option_macros(self, option_values):
        result = []
        for option_value in (x for x in option_values
            if type(x.option) == CompilerOption and
            x.option.test_category(PreprocessingCategory)):
            result += token.option.get_macros(token.val)
        return result

    def requires_preprocessing(self, file):
        return False

    def compile_cpp(self, manager, source, obj, includes, locally=False):
        raise NotImplementedError()

class TaskCreator:
    def __init__(self, compiler_wrapper, command):
        self.__executable = compiler_wrapper.compiler_executable()
        self.__compiler = compiler_wrapper
        self.__option_values = list(compiler_wrapper.parse_options(command[1:]))

    def executable(self):
        return self.__executable

    def option_values(self):
        return self.__option_values

    def free_options(self):
        return (token for token in self.option_values() if type(token.option) == FreeOption)

    def filter_options(self, filter):
        if type(filter) == type and issubclass(filter, Category):
            return (token for token in self.option_values()
                if type(token.option) == CompilerOption and
                token.option.test_category(filter))
        if isinstance(filter, CompilerOption):
            return (token for token in self.option_values()
                if token.option.name() == filter.name())
        raise RuntimeError("Unknown option filter.")

    def input_files(self):
        return (input.make_str() for input in self.free_options())

    def build_local(self):
        tokens = list(self.filter_options(BuildLocalCategory))
        if not tokens:
            return False

        print("Command requires local compilation.")
        return True

    def create_tasks(self):
        # See if user specified an explicit name for the object file.
        output = list(self.filter_options(self.__compiler.object_name_option()))
        if output:
            output = output[-1].val
        sources = [input for input in self.input_files() if self.__compiler.requires_preprocessing(input)]
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__compiler.object_name_option.esc(), self.__compiler.object_name_option.name()))

        preprocess_call = [self.executable()]
        preprocess_call.extend(option.make_str() for option in 
            self.filter_options(PreprocessingCategory))
        preprocess_call.append(self.__compiler.preprocess_option().make_value().make_str())

        compile_call = [self.executable()]
        compile_call.extend(option.make_str() for option in
            self.filter_options(CompilationCategory))

        includes = [os.path.join(os.getcwd(), token.val) for token in self.filter_options(self.__compiler.include_option())]
        macros = [token.val for token in self.filter_options(self.__compiler.define_option())]
        sysincludes = os.getenv('INCLUDE', '').split(';')

        pch_header = list(self.filter_options(self.__compiler.use_pch_option()))
        if pch_header:
            assert len(pch_header) == 1
            pch_header = pch_header[0].val
            pch_file = list(self.filter_options(self.__compiler.pch_file_option()))
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
                compiler_executable = self.executable(),
                call = compile_call,
                cwd = os.getcwd(),
                source = source,
                source_type = os.path.splitext(source)[1],
                preprocessor_info = PreprocessorInfo(macros, self.__compiler.compiler_option_macros(self.option_values()), includes, sysincludes),
                output = os.path.join(os.getcwd(), output or os.path.splitext(source)[0] + '.obj'),
                pch_file = pch_file,
                pch_header = pch_header)

        self.tasks = [(preprocess_call + [source], create_task(source)) for source in sources]

    def should_invoke_linker(self):
        return self.__compiler.compile_no_link_option() not in [token.option for token in self.option_values()]

    def postprocess(self):
        if not self.should_invoke_linker():
            return False, None

        print("Linking...")
        objects = {}
        for preprocess_call, task in self.tasks:
            objects[task.source] = task.output

        call = [self.executable()]
        call.extend(o.make_str() for o in
            self.filter_options(LinkingCategory))
        for input in self.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        return True, subprocess.call(call)

def execute_remotely(compiler_wrapper, tasks, port):
    zmq_ctx = zmq.Context()
    conn = zmq_ctx.socket(zmq.DEALER)
    conn.connect("tcp://localhost:{}".format(port))
    for preprocess_call, compile_task in tasks:
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
            elif request == "GET_COMPILER_INFO":
                conn.send_pyobj(compiler_wrapper.compiler_info(compile_task.compiler_executable))
            elif request == "FAILED":
                return -1
            else:
                print("GOT {}".format(request))
                return -1

def execute(compiler_wrapper, command, force_local=False):
    ctx = TaskCreator(compiler_wrapper, command[1:])
    if ctx.build_local() or force_local:
        call = [ctx.executable()]
        call.extend(option.make_str() for option in ctx.option_values())
        return subprocess.call(call)
    ctx.create_tasks()
    retcode = execute_remotely(compiler_wrapper, ctx.tasks, command[0])
    postprocessed, result = ctx.postprocess()
    if postprocessed:
        return result
    return retcode

