from .utils import *
from .message import MessageProtocol, msg_to_bytes

class ServerTask:
    def __init__(self, fqdn, compiler_info, call, pch_file, pch_header, includes, src_decorator):
        self.fqdn = fqdn
        self.compiler_info = compiler_info
        self.call = call
        self.pch_header = pch_header
        self.pch_file = pch_file
        self.includes = includes
        self.src_decorator = src_decorator
        self.filelist = None

class CompilerInfo:
    def __init__(self, toolset, executable, compiler_id, macros):
        self.toolset = toolset
        self.executable = executable
        self.id = compiler_id
        self.macros = macros
        self.files = None

    def set_files(self, files):
        self.files = files