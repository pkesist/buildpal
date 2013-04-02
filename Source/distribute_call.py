

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
import tempfile
import bz2

from multiprocessing.connection import Client


class CmdLineOption:
    class Value:
        def __init__(self, option, esc, sep, val):
            self.option = option
            self.esc = esc
            self.sep = sep
            self.val = val

        def __str__(self):
            return ("<CmdLineOption.Value object: Option: '{}{}', Value: '{}'>"
                .format(self.sep, self.option.name(), self.val))

        def make_str(self):
            return "{}{}{}{}".format(
                self.esc or (self.option.esc() if self.option else ''),
                self.option.name() if self.option else '',
                self.sep or '',
                self.val or '')

    def __init__(self, name, esc, has_arg=True, allow_spaces=True, allow_equal=True, default_separator=None):
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
        self.__def_sep = default_separator or (' ' if allow_spaces else '=' if allow_equal else '')

    def __value_regex(self):
        if not self.__has_arg: return "$"
        if self.__allow_equal:
            return r"(\=(?P<val>.+))?$"
        return r"(?P<val>.+)?$"

    def name(self):
        return self.__name
        
    def esc(self):
        return self.__esc[0]

    def __make_match(self, esc, sep, val):
        return CmdLineOption.Value(self, esc, sep, val)

    def make_value(self, val):
        return CmdLineOption.Value(self, self.esc(), self.__def_sep, val)

    def parse(self, option, iter):
        regex = r"^(?P<esc>.*){name}{end}".format(name=self.__name,
            end=self.__value_regex())
        match = re.match(regex, option)
        if not match:
            return None
        esc = match.group('esc')
        if not esc in self.__esc:
            return None

        name = self.name()
        if not self.__has_arg:
            return self.__make_match(esc, None, None)

        val = match.group('val')
        if val is not None:
            return self.__make_match(esc, '=' if self.__allow_equal else '', val)

        if self.__allow_spaces:
            try:
                x = next(iter)
                return self.__make_match(esc, ' ', x)
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
        return CmdLineOption.Value(FreeOption(), None, None, token)
        

class Distributor:
    def create_local_invocation(self, command):
        raise NotImplementedError("Distributor.create_local_invocation")

    def preprocess(self, local_invocation):
        raise NotImplementedError("Distributor.preprocess")

    def create_remote_invocation(self, command, preprocessed):
        raise NotImplementedError("Distributor.create_remote_invocation")

    def execute_remotely(self, remote_invocation):
        raise NotImplementedError("Distributor.execute_remotely")

    def postprocess(self, remote_result):
        return remote_result

    def execute(self, command):
        local_inv = self.create_local_invocation(command)
        preprocessed = self.preprocess(local_inv)
        remote_inv = self.create_remote_invocation(command, preprocessed)
        remote_result = self.execute_remotely(remote_inv)
        return self.postprocess(remote_result)


class CompilationDistributer(Distributor, CmdLineOptions):
    class LocalOption(CmdLineOption): pass
    class RemoteOption(CmdLineOption): pass
    
    def __init__(self, preprocess, name):
        self.__preprocess = preprocess
        self.__name = name
        CmdLineOptions.add_option(self, self.__name)

    def add_option(self, option):
        assert(isinstance(option, CompilationDistributer.LocalOption) or
            isinstance(option, CompilationDistributer.RemoteOption))
        CmdLineOptions.add_option(self, option)

    def get_tokens(self, command, condition):
        for token in self.parse_options(command):
            if condition(token):
                yield token

    def create_local_invocation(self, command):
        command = shlex.split(command)
        print("Processing '{}'.".format(command))
        executable = command[0]
        command = command[1:]
        tokens = list(self.get_options(command, CompilationDistributer.LocalOption))
        tokens.append(CmdLineOption.Value(self.__preprocess, None, None, None))
        preprocessing_tasks = []
        output = list(self.get_tokens(command, lambda token : token.option == self.__name))
        if output:
            output = output[-1]
        else:
            output = None

        inputs = list(self.get_options(command, FreeOption))
        if output and len(inputs) > 1:
            raise RuntimeError("Cannot use {} with multiple sources.".format(self.__name.name()))
        for input in inputs:
            file, filename = tempfile.mkstemp(text=True)
            source = input.make_str()
            preprocessing_tasks.append((input, file, filename, output or os.path.splitext(source)[0] + '.obj'))
            
        class LocalInvocation(object): pass
        local_invocation = LocalInvocation()
        local_invocation.executable = executable
        local_invocation.tokens = tokens
        local_invocation.tasks = preprocessing_tasks
        return local_invocation

    def preprocess(self, local_invocation):
        print(local_invocation)
        call = [local_invocation.executable]
        call += [option.make_str() for option in local_invocation.tokens]
        for task in local_invocation.tasks:
            local_call = call + [task[0].make_str()]
            print("Executing '{}' locally.".format(local_call))
            subprocess.check_call(local_call, stdout=task[1], stderr=subprocess.PIPE)
            os.close(task[1])
        class Preprocessed: pass
        preprocessed = Preprocessed()
        preprocessed.files = [(task[2], task[3]) for task in local_invocation.tasks]
        return preprocessed

    def create_remote_invocation(self, command, preprocessed):
        command = shlex.split(command)
        executable = command[0]
        command = command[1:]
        tokens = list(self.get_options(command, CompilationDistributer.RemoteOption))
        tokens.append(CmdLineOption.Value(None, None, None, "/TP"))
        class RemoteInvocation(object): pass
        remote_invocation = RemoteInvocation()
        setattr(remote_invocation, 'executable', executable)
        setattr(remote_invocation, 'tokens', tokens)
        setattr(remote_invocation, 'files', preprocessed.files)
        return remote_invocation

    @classmethod
    def server_function(conn):
        import tempfile
        import bz2
        import os
        import subprocess

        call = conn.recv()
        count = conn.recv()
        files = []

        def receive_file():
            more = True
            fileDesc, filename = tempfile.mkstemp()
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
                local_call = call + [file, "/Fo{}".format(objectFilename)]
                print(local_call)
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
        conn = Client(address)
        conn.send(marshal.dumps(CompilationDistributer.server_function.__code__))
        conn.send(call)
        conn.send(len(remote_invocation.files))
        for file, object in remote_invocation.files:
            compressor = bz2.BZ2Compressor()
            with open(file, 'rb') as file:
                data = file.read(4096)
                while data:
                    conn.send((True, compressor.compress(data)))
                    data = file.read(4096)
                conn.send((False, compressor.flush()))
        
        incoming_len = conn.recv()
        assert(incoming_len == len(remote_invocation.files))
        for file, object in remote_invocation.files:
            retcode, stdout, stderr = conn.recv()
            if retcode == 0:
                more = True
                with open(object, "wb") as file:
                    while more:
                        more, data = conn.recv()
                        file.write(data)
                print("Got '{}' from server.".format(object))
        

def test_cmdline_options():
    options = CmdLineOptions()
    options.add_option(CmdLineOption(*['x', '-', False]))
    options.add_option(CmdLineOption(*['I', '-', True ]))
    options.add_option(CmdLineOption(**{ 'name' : 'o', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : True , 'allow_equal' : False}))
    options.add_option(CmdLineOption(**{ 'name' : 'O', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : False, 'allow_equal' : True}))
    options.add_option(CmdLineOption(**{ 'name' : 'G', 'esc' : '-', 'has_arg' : True, 'allow_spaces' : False, 'allow_equal' : False}))
        
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

def test_compiler_separation():
    preprocess=CmdLineOption('E', '/', False)
    name=CmdLineOption('Fo', '/', True, False, False)
    distributer = CompilationDistributer(preprocess, name)
    distributer.add_option(CompilationDistributer.LocalOption('I', '-', True, True, False))
    distributer.add_option(CompilationDistributer.LocalOption('D', '-', True, False, False))
    distributer.add_option(CompilationDistributer.RemoteOption('c', '-', False, False, False))
    distributer.add_option(CompilationDistributer.RemoteOption('EHsc', '/', False, False, False))
    distributer.execute('cl.exe /EHsc -DTEST -DTEST=asdf -I"LALALA lala" -c test.cpp test2.cpp')

if __name__ == "__main__":
    test_compiler_separation()
    
