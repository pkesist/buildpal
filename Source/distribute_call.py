

# call -----> analyze                                      -----> local_invocation
#                                                          -----> remote_invocation
#      -----> preprocess(local_invocation)                 -----> local_output
#      -----> remote_call(local_output, remote_invocation) -----> remote output
#      -----> postprocess call(remote_output)              -----> output

import re
import shlex
import marshal
import os
import subprocess
import sys
import tempfile
import bz2

from multiprocessing.connection import Client


class CmdLineOption:
    class Value:
        def __init__(self, option, esc, suf, sep, val):
            self.option = option
            self.esc = esc
            self.sep = sep
            self.suf = suf
            self.val = val

        def __str__(self):
            return ("<CmdLineOption.Value object: '{}'>"
                .format(self.make_str()))

        def make_str(self):
            return "{}{}{}{}{}".format(
                self.esc or (self.option.esc() if self.option else ''),
                self.option.name() if self.option else '',
                self.suf or '',
                self.sep or '',
                self.val or '')

    def __init__(self, name, esc, suff=None, has_arg=True, allow_spaces=True, allow_equal=True, default_separator=None):
        self.__name = name
        self.__has_arg = has_arg
        self.__allow_spaces = allow_spaces
        self.__allow_equal = allow_equal
        if esc is None:
            raise RuntimeError("Command line option must have escape sequence defined.")
        if isinstance(esc, str):
            esc = [esc]
        if not isinstance(esc, list):
            raise RuntimeError("Escape sequence parameter must be a string or list of strings.")
        self.__esc = esc
        self.__suff = suff
        self.__def_sep = '' if not self.__has_arg else default_separator or (' ' if allow_spaces else '=' if allow_equal else '')

    def __value_regex(self):
        result = []
        result.append("(?P<suf>{})?".format(re.escape(self.__suff if self.__suff else '')))
        if not self.__has_arg:
            result.append("$")
            return "".join(result)
        if self.__allow_equal:
            result.append(r"(\=(?P<val>.+))?$")
        else:
            result.append(r"(?P<val>.+)?$")
        return "".join(result)

    def name(self):
        return self.__name
        
    def esc(self):
        return self.__esc[0]

    def __make_match(self, esc, suf, sep, val):
        return CmdLineOption.Value(self, esc, suf, sep, val)

    def make_value(self, val=None):
        return CmdLineOption.Value(self, self.esc(), '', self.__def_sep, val)

    def parse(self, option, iter):
        regex = r"^(?P<esc>.*){name}{end}".format(name=re.escape(self.__name),
            end=self.__value_regex())
        match = re.match(regex, option)
        if not match:
            return None
        esc = match.group('esc')
        if not esc in self.__esc:
            return None
        name = self.name()
        suf = match.group('suf')
        if not self.__has_arg:
            return self.__make_match(esc, suf, None, None)

        val = match.group('val')
        if val is not None:
            return self.__make_match(esc, suf, '=' if self.__allow_equal else '', val)

        if self.__allow_spaces:
            try:
                x = next(iter)
                return self.__make_match(esc, suf, ' ', x)
            except StopIteration:
                # Fall through to exception below
                pass 

        raise RuntimeError("Missing value for option '{}'.".format(option))

class FreeOption:
    def name(self): return ''
    def esc(self): return ''
        
class CmdLineOptions:
    __options = []

    def add_option(self, option):
        self.__options.append(option)

    def __parse_option(self, tokenIter):
        while True:
            try:
                token = next(tokenIter)
                match = None
                for option in self.__options:
                    match = option.parse(token, tokenIter)
                    if match:
                        break
                if match:
                    yield match
                else:
                    yield self.__free_option(token)
            except StopIteration:
                break

    def parse_options(self, options):
        return self.__parse_option( (option for option in options) )

    def get_options(self, command, types):
        if isinstance(types, type):
            types = [types]
        for token in self.parse_options(command):
            if type(token.option) in types:
                yield token

    def __free_option(self, token):
        return CmdLineOption.Value(FreeOption(), None, None, None, token)
        

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
    class PreprocessingOption(CmdLineOption): pass
    class CompilationOption(CmdLineOption): pass

    class Context:
        def __init__(self, command, option_parser):
            self.__executable = command[0]
            self.__options = list(option_parser.parse_options(command[1:]))

        def executable(self): return self.__executable
        def options(self): return self.__options
        
        def filter_options(self, filter):
            callable = filter
            if isinstance(filter, type):
                callable = lambda token : type(token.option) == filter
            for token in self.__options:
                if callable(token):
                    yield token

        def source_files(self):
            return (input.make_str() for input in self.filter_options(FreeOption))

        
    def create_context(self, command):
        print("Processing '{}'.".format(command))
        result = CompilationDistributer.Context(command, self)
        return result

    def __init__(self, preprocess_option, obj_name_option, compile_no_link_option):
        self.__preprocess = preprocess_option
        self.__name = obj_name_option
        self.__compile = compile_no_link_option
        CmdLineOptions.add_option(self, self.__name)
        CmdLineOptions.add_option(self, self.__compile)

    def add_option(self, option):
        assert (isinstance(option, CompilationDistributer.PreprocessingOption) or
            isinstance(option, CompilationDistributer.CompilationOption))
        CmdLineOptions.add_option(self, option)

    def should_invoke_linker(self, ctx):
        return True

    def get_source_files(self, ctx):
        return ctx.source_files()

    def preprocess(self, ctx):
        tokens = list(ctx.filter_options(CompilationDistributer.PreprocessingOption))
        tokens.append(CmdLineOption.Value(self.__preprocess, None, None, None, None))
        # See if user specified an explicit name for the object file.
        output = list(ctx.filter_options(lambda token : token.option == self.__name))
        if output:
            output = output[-1].val
        else:
            output = None
        sources = list(self.get_source_files(ctx))
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__name.esc(), self.__name.name()))
        class PreprocessingTask: pass

        call = [ctx.executable()]
        call.extend(option.make_str() for option in tokens)

        ctx.tasks = []
        for source in sources:
            task = PreprocessingTask()
            task.source = source
            task.object = output or os.path.splitext(source)[0] + '.obj'
            task.type = os.path.splitext(source)[1]
            file, filename = tempfile.mkstemp(text=True)
            local_call = call + [task.source]
            print("Executing '{}' locally.".format(local_call))
            subprocess.check_call(local_call, stdout=file, stderr=subprocess.PIPE)
            os.close(file)
            task.filename = filename
            ctx.tasks.append(task)

    def execute_remotely(self, ctx):
        tokens = list(ctx.filter_options(CompilationDistributer.CompilationOption))
        call = [ctx.executable()]
        call += [option.make_str() for option in tokens]
        address = ('localhost', 6000)
        param = {'outputOption' : self.__name.make_value('{}').make_str(),
            'compileNoLink' : self.__compile.make_value().make_str()}
        conn = Client(address)
        conn.send((marshal.dumps(CompilationDistributer.server_function.__code__), param))
        conn.send(call)
        conn.send(len(ctx.tasks))
        for task in ctx.tasks:
            conn.send(task.type)
            compressor = bz2.BZ2Compressor()
            with open(task.source, 'rb') as file:
                data = file.read(4096)
                while data:
                    conn.send((True, compressor.compress(data)))
                    data = file.read(4096)
                conn.send((False, compressor.flush()))
        
        incoming_len = conn.recv()
        assert incoming_len == len(ctx.tasks)
        errors = False
        for task in ctx.tasks:
            retcode, stdout, stderr = conn.recv()
            sys.stderr.write("---------------------------- STDERR ----------------------------\n")
            sys.stderr.write(stderr.decode())
            sys.stderr.write("----------------------------------------------------------------\n")
            sys.stdout.write("---------------------------- STDOUT ----------------------------\n")
            sys.stdout.write(stdout.decode())
            sys.stdout.write("----------------------------------------------------------------\n")
            if retcode == 0:
                more = True
                with open(task.object, "wb") as file:
                    while more:
                        more, data = conn.recv()
                        file.write(data)
            else:
                errors = True
        if errors:
            raise RuntimeError("Errors occurred during remote compilation.")

    @classmethod
    def server_function(param, conn):
        import tempfile
        import bz2
        import os
        import subprocess

        call = conn.recv()
        print(call)
        count = conn.recv()
        files = []

        def receive_file():
            more = True
            type = conn.recv()
            fileDesc, filename = tempfile.mkstemp(suffix="{}".format(type))
            decompressor = bz2.BZ2Decompressor()
            with os.fdopen(fileDesc, "wb") as file:
                while more:
                    more, data = conn.recv()
                    file.write(decompressor.decompress(data))
            return filename

        def send_file(name):
            with open(name, "rb") as file:
                data = file.read(4096)
                while data:
                    conn.send((True, data))
                    data = file.read(4096)
                conn.send((False, data))

        for i in range(count):
            files.append(receive_file())
        
        result = []
        try:
            conn.send(len(files))
            fileDesc, objectFilename = tempfile.mkstemp(suffix=".obj")
            os.close(fileDesc)
            for file in files:
                local_call = call + [param['compileNoLink'], file, param['outputOption'].format(objectFilename)]
                print(" ".join(local_call))
                with subprocess.Popen(local_call, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                    output = proc.communicate()
                    conn.send((proc.returncode, output[0], output[1],))
                if proc.returncode == 0:
                    send_file(objectFilename)
        except:
            import traceback
            traceback.print_exc()
            raise

    def postprocess(self, ctx):
        if not self.should_invoke_linker(ctx):
            return

        objects = {}
        for task in ctx.tasks:
            objects[task.filename] = task.object

        call = [ctx.executable()]
        for input in self.get_source_files(ctx):
            if input in objects:
                call.append(objects[input])
            else:
                call.append(input)
        retcode = subprocess.call(call)
        sys.exit(retcode)
        
        
        

def test_cmdline_options():
    options = CmdLineOptions()
    options.add_option(CmdLineOption(*['x', '-', False]))
    options.add_option(CmdLineOption(*['I', '-', True ]))
    options.add_option(CmdLineOption(**{'name' : 'o', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : True , 'allow_equal' : False}))
    options.add_option(CmdLineOption(**{'name' : 'O', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : False, 'allow_equal' : True}))
    options.add_option(CmdLineOption(**{'name' : 'G', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : False, 'allow_equal' : False}))
        
    input = [
        "-x",
        "-I asdf",
        "-I=asdf",
        "-o asdf",
        "-oasdf",
        "-O=asdf",
        "-Gasdf",
        "-x -I asdf -I=asdf -o asdf -oasdf -O=asdf -Gasdf"]
    for command in input:
        tokens = options.parse_options(shlex.split(command))
        for token in tokens:
            print(token, token.option.type())
