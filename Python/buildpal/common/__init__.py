from .utils import *
from .message import MessageProtocol, msg_to_bytes

class ServerTask:
    def __init__(self, fqdn, compiler_info, call, pch_file, pdb_file=None):
        self.fqdn = fqdn
        self.compiler_info = compiler_info
        self.call = call
        self.pch_file = pch_file
        self.pdb_file = pdb_file
        self.filelist = None

class CompilerInfo:
    def __init__(self, toolset, executable, id, macros):
        self.toolset = toolset
        self.executable = executable
        self.id = id
        self.macros = macros
        self.files = None

    def set_files(self, files):
        self.files = files