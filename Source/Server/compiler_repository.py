import os
import tempfile
import hashlib
import pickle

from threading import Lock
from collections import defaultdict

class CompilerRepository:
    def __init__(self):
        self.__dir = os.path.join(tempfile.gettempdir(), 'BuildPal', 'Compilers')
        self.__lock = Lock()
        self.__compilers = set()
        self.__partial_compilers = set()
        self.__waiters = defaultdict(list)

    @classmethod
    def __unique_id(cls, compiler_id):
        digest = hashlib.md5()
        digest.update(pickle.dumps(compiler_id))
        return digest.hexdigest()

    def compiler_dir(self, compiler_id):
        return os.path.join(self.__dir, self.__unique_id(compiler_id))

    def compiler_required(self, compiler_id):
        id = self.__unique_id(compiler_id)
        with self.__lock:
            if id in self.__compilers:
                assert os.path.exists(self.compiler_dir(compiler_id))
                return False
            if os.path.exists(self.compiler_dir(compiler_id)):
                self.__compilers.add(id)
                return False
            if id in self.__partial_compilers:
                return False
            self.__partial_compilers.add(id)
            return True

    def when_compiler_is_available(self, compiler_id, handler):
        id = self.__unique_id(compiler_id)
        with self.__lock:
            assert id in self.__compilers or id in self.__partial_compilers
            if id in self.__compilers:
                handler()
            else:
                self.__waiters[id].append(handler)

    def set_compiler_ready(self, compiler_id):
        id = self.__unique_id(compiler_id)
        with self.__lock:
            assert id in self.__partial_compilers
            assert id not in self.__compilers
            assert os.path.exists(self.compiler_dir(compiler_id))
            self.__partial_compilers.remove(id)
            self.__compilers.add(id)
        for handler in self.__waiters[id]:
            handler()
        del self.__waiters[id]
