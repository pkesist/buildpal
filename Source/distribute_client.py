from cmdline_processing import FreeOption, CmdLineOption, CmdLineOptions
from distribute_task import CompileTask
from distribute_manager import DistributeManager

import os
import random
import subprocess
import string
import sys
import zlib

from tempfile import mkstemp
from multiprocessing.connection import Listener
from multiprocessing.managers import BaseManager

class Distributer:
    def create_context(self, command):
        raise NotImplementedError("Distributer.create_context")

    def bailout(self, context):
        return False

    def preprocess(self, context):
        raise NotImplementedError("Distributer.preprocess")

    def execute_remotely(self, context, remote_invocation):
        raise NotImplementedError("Distributer.execute_remotely")

    def postprocess(self, context):
        pass
    
    def execute(self, command):
        ctx = self.create_context(command)
        if self.bailout(ctx):
            return
        self.preprocess(ctx)
        self.execute_remotely(ctx)
        self.postprocess(ctx)


class Preprocessor:
    def __init__(self, preprocess_call):
        self.__preprocessed = False
        self.__preprocess_call = preprocess_call
        file, self.__filename = mkstemp(text=True)
        os.close(file)

    def preprocess(self):
        p = subprocess.Popen(self.__preprocess_call, stdout=subprocess.PIPE)
        with open(self.__filename, 'wb') as file:
            compressor = zlib.compressobj(1)
            for data in iter(lambda : p.stdout.read(10 * 1024), b''):
                compressed = compressor.compress(data)
                file.write(compressed)
            compressed = compressor.flush(zlib.Z_FINISH)
            file.write(compressed)
        self.__preprocessed = True

    def filename(self):
        return self.__filename

    def __enter__(self):
        if not self.__preprocessed:
            self.preprocess()
        self.__file = open(self.__filename, 'rb')
        return self.__file

    def __exit__(self, exc_type, exc_value, traceback):
        self.__file.close()
        try:
            os.remove(self.__filename)
        except:
            pass


class CompilerInfo:
    def __init__(self, toolset, executable, size, id):
        self.__toolset = toolset
        self.__executable = executable
        self.__size = size
        self.__id = id

    def toolset(self): return self.__toolset
    def executable(self): return self.__executable
    def size(self): return self.__size
    def id(self): return self.__id

class CompilationDistributer(Distributer, CmdLineOptions):
    class Category: pass
    class BailoutCategory(Category): pass
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
                self.__manager = DistributeManager(r"\\.\pipe\{}".format(self.__manager_id), b"")
                self.__manager.connect()
            except:
                raise EnvironmentError("Failed to connect to build manager "
                    "'{}'.".format(manager_id))

        def queue_task(self, task, endpoint):
            self.__manager.queue_task(task, endpoint)

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
        
    def bailout(self, ctx):
        tokens = list(ctx.filter_options(CompilationDistributer.BailoutCategory))
        if not tokens:
            return False

        print("Command does not require distributed compilation. Running locally.")
        call = [ctx.executable()]
        call.extend(option.make_str() for option in ctx.options())
        subprocess.check_call(call)
        return True

    def create_context(self, command):
        return CompilationDistributer.Context(command, self)

    def compiler_info(self, executable):
        raise NotImplementedError("Compiler identification not implemented.")

    def __init__(self, preprocess_option, obj_name_option, compile_no_link_option):
        self.__preprocess = preprocess_option
        self.__object_name_option = obj_name_option
        self.__compile_no_link_option = compile_no_link_option
        self.__compile_no_link_option.add_category(CompilationDistributer.CompilationCategory)
        self.add_option(self.__compile_no_link_option)
        self.add_option(self.__object_name_option)

    def object_name_option(self):
        return self.__object_name_option

    def compile_no_link_option(self):
        return self.__compile_no_link_option

    def should_invoke_linker(self, ctx):
        return self.compile_no_link_option() not in [token.option for token in ctx.options()]

    def requires_preprocessing(self, file):
        return False

    def preprocess(self, ctx):
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
            ctx.filter_options(CompilationDistributer.PreprocessingCategory))
        preprocess_call.append(self.__preprocess.make_value().make_str())

        compile_call = [ctx.executable()]
        compile_call.extend(option.make_str() for option in
            ctx.filter_options(CompilationDistributer.CompilationCategory))

        def make_task(source):
            preprocessor = Preprocessor(preprocess_call + [source])
            task = CompileTask(
                call = compile_call,
                source = source,
                source_type = os.path.splitext(source)[1],
                input = preprocessor.filename(),
                output = os.path.join(os.getcwd(), output or os.path.splitext(source)[0] + '.obj'),
                compiler_info = self.compiler_info(ctx.executable()),
                distributer = self)
            return preprocessor, task

        ctx.tasks = [make_task(source) for source in sources]

    def execute_remotely(self, ctx):
        rnd = random.Random()
        rnd.seed()
        endpoint = "".join(rnd.choice(string.ascii_uppercase) for x in range(15))
        listener = Listener(r'\\.\pipe\{}'.format(endpoint), b"")
        for preprocessor, compile_task in ctx.tasks:
            ctx.queue_task(compile_task, endpoint)
            conn = listener.accept()
            # Wait for preprocess signal.
            preprocess = conn.recv()
            preprocessor.preprocess()
            conn.send(True)
            retcode, stdout, stderr = conn.recv()
            sys.stdout.write(stdout.decode())
            if stderr:
                sys.stderr.write("---------------------------- STDERR ----------------------------\n")
                sys.stderr.write(stderr.decode())
                sys.stderr.write("----------------------------------------------------------------\n")
            if retcode == 0:
                done = conn.recv()
        listener.close()

    def postprocess(self, ctx):
        if not self.should_invoke_linker(ctx):
            return

        print("Linking...")
        objects = {}
        for task in ctx.tasks:
            objects[task.source] = task.object

        call = [ctx.executable()]
        call.extend(o.make_str() for o in
            ctx.filter_options(CompilationDistributer.LinkingCategory))
        for input in ctx.input_files():
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        print("Calling '{}'.".format(call))
        subprocess.check_call(call)
