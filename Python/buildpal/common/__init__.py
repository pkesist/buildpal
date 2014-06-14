from .utils import *
from .message import MessageProtocol

class ServerTask:
    def __init__(self, fqdn, compiler_info, call, pch_file, pdb_file=None):
        self.fqdn = fqdn
        self.compiler_info = compiler_info
        self.call = call
        self.pch_file = pch_file
        self.pdb_file = pdb_file
