

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
        

class Distributor:
    def create_preprocessing_info(self, command):
        raise NotImplementedError("Distributor.create_preprocessing_info")

    def preprocess(self, local_invocation):
        raise NotImplementedError("Distributor.preprocess")

    def create_remote_invocation(self, command, preprocessed):
        raise NotImplementedError("Distributor.create_remote_invocation")

    def execute_remotely(self, remote_invocation):
        raise NotImplementedError("Distributor.execute_remotely")

    def postprocess(self, command, remote_result):
        pass

    def execute(self, command):
        preprocessing_info = self.create_preprocessing_info(command)
        preprocessed = self.preprocess(preprocessing_info)
        remote_inv = self.create_remote_invocation(command, preprocessed)
        remote_result = self.execute_remotely(remote_inv)
        self.postprocess(command, remote_result)


class CompilationDistributer(Distributor, CmdLineOptions):
    class PreprocessingOption(CmdLineOption): pass
    class CompilationOption(CmdLineOption): pass
    
    def __init__(self, preprocess_option, obj_name_option, compile_no_link_option):
        self.__preprocess = preprocess_option
        self.__name = obj_name_option
        self.__compile = compile_no_link_option
        CmdLineOptions.add_option(self, self.__name)
        CmdLineOptions.add_option(self, self.__compile)

    def add_option(self, option):
        assert(isinstance(option, CompilationDistributer.PreprocessingOption) or
            isinstance(option, CompilationDistributer.CompilationOption))
        CmdLineOptions.add_option(self, option)

    def get_tokens(self, command, condition):
        for token in self.parse_options(command):
            if condition(token):
                yield token

    def __get_source_files(self, command):
        # This should be handled better.
        # Currently we expect there is no /TC, /TP,
        # /Tc or /Tp options on the command line
        inputs = [input.make_str() for input in self.get_options(command, FreeOption)]
        for input in inputs:
            if os.path.splitext(input)[1].lower() in ['.c', '.cpp', '.cxx']:
                yield input

    def should_invoke_linker(self, command):
        return True

    def create_preprocessing_info(self, command):
        print("Processing '{}'.".format(command))
        executable = command[0]
        command = command[1:]
        tokens = list(self.get_options(command, CompilationDistributer.PreprocessingOption))
        tokens.append(CmdLineOption.Value(self.__preprocess, None, None, None, None))
        preprocessing_tasks = []
        # See if user specified an explicit name for the object file.
        output = list(self.get_tokens(command, lambda token : token.option == self.__name))
        if output:
            output = output[-1].val
        else:
            output = None
        sources = list(self.__get_source_files(command))
        if output and len(sources) > 1:
            raise RuntimeError("Cannot use {}{} with multiple sources."
                .format(self.__name.esc(), self.__name.name()))
        class PreprocessingTask: pass
        for source in sources:
            file, filename = tempfile.mkstemp(text=True)
            task = PreprocessingTask()
            task.source = source
            task.file = file
            task.filename = filename
            task.object = output or os.path.splitext(source)[0] + '.obj'
            task.type = os.path.splitext(source)[1]
            preprocessing_tasks.append(task)
            
        class PreprocessingInfo(object): pass
        preprocessing_info = PreprocessingInfo()
        preprocessing_info.executable = executable
        preprocessing_info.tokens = tokens
        preprocessing_info.tasks = preprocessing_tasks
        return preprocessing_info

    def preprocess(self, preprocessing_info):
        call = [preprocessing_info.executable]
        call += [option.make_str() for option in preprocessing_info.tokens]
        files = []
        for task in preprocessing_info.tasks:
            local_call = call + [task.source]
            print("Executing '{}' locally.".format(local_call))
            subprocess.check_call(local_call, stdout=task.file, stderr=subprocess.PIPE)
            os.close(task.file)
        class Preprocessed: pass
        preprocessed = Preprocessed()
        preprocessed.files = [(task.filename, task.object, task.type, task.source) for task in preprocessing_info.tasks]
        return preprocessed

    def create_remote_invocation(self, command, preprocessed):
        executable = command[0]
        command = command[1:]
        tokens = list(self.get_options(command, CompilationDistributer.CompilationOption))
        class RemoteInvocation(object): pass
        remote_invocation = RemoteInvocation()
        setattr(remote_invocation, 'executable', executable)
        setattr(remote_invocation, 'tokens', tokens)
        setattr(remote_invocation, 'files', preprocessed.files)
        return remote_invocation

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

    def execute_remotely(self, remote_invocation):
        call = [remote_invocation.executable]
        call += [option.make_str() for option in remote_invocation.tokens]
        address = ('localhost', 6000)
        param = {'outputOption' : self.__name.make_value('{}').make_str(),
            'compileNoLink' : self.__compile.make_value().make_str()
        }
        conn = Client(address)
        conn.send((marshal.dumps(CompilationDistributer.server_function.__code__), param))
        conn.send(call)
        conn.send(len(remote_invocation.files))
        for file, object, type, source in remote_invocation.files:
            conn.send(type)
            compressor = bz2.BZ2Compressor()
            with open(file, 'rb') as file:
                data = file.read(4096)
                while data:
                    conn.send((True, compressor.compress(data)))
                    data = file.read(4096)
                conn.send((False, compressor.flush()))
        
        incoming_len = conn.recv()
        assert(incoming_len == len(remote_invocation.files))
        errors = False
        objects = {}
        for file, object, type, source in remote_invocation.files:
            retcode, stdout, stderr = conn.recv()
            sys.stderr.write("---------------------------- STDERR ----------------------------\n")
            sys.stderr.write(stderr.decode())
            sys.stderr.write("----------------------------------------------------------------\n")
            sys.stdout.write("---------------------------- STDOUT ----------------------------\n")
            sys.stdout.write(stdout.decode())
            sys.stdout.write("----------------------------------------------------------------\n")
            if retcode == 0:
                more = True
                with open(object, "wb") as file:
                    while more:
                        more, data = conn.recv()
                        file.write(data)
                objects[source] = object
            else:
                errors = True
        if errors:
            raise RuntimeError("Errors occurred during remote compilation.")
        class RemoteResult: pass
        remoteResult = RemoteResult()
        remoteResult.objects = objects
        return remoteResult

    def postprocess(self, command, remote_result):
        executable = command[0]
        command = command[1:]
        if not self.should_invoke_linker(command):
            return
        call = [executable]
        inputs = [input.make_str() for input in self.get_options(command, FreeOption)]
        for input in inputs:
            if input in remote_result.objects:
                call.append(remote_result.objects[input])
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
