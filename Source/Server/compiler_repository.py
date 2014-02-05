import os
import tempfile
import hashlib
import pickle

from threading import Lock

class CompilerRepository:
    def __init__(self):
        self.__dir = os.path.join(tempfile.gettempdir(), 'BuildPal', 'Compilers')
        os.makedirs(self.__dir, exist_ok=True)
        self.__lock = Lock()
        self.__compilers = set()
        self.__partial_compilers = set()

    @classmethod
    def __unique_id(cls, compiler_id):
        digest = hashlib.md5()
        digest.update(pickle.dumps(compiler_id))
        return digest.hexdigest()

    def compiler_dir(self, compiler_id):
        return os.path.join(self.__dir, self.__unique_id(compiler_id))

    def has_compiler(self, compiler_id):
        id = self.__unique_id(compiler_id)
        with self.__lock:
            if id in self.__compilers:
                assert os.path.exists(self.compiler_dir(compiler_id))
                return True
            if id in self.__partial_compilers:
                return False
            if os.path.exists(self.compiler_dir(compiler_id)):
                self.__compilers.add(compiler_id)
                return True
            self.__partial_compilers.add(id)
            return None

    def set_compiler_ready(self, compiler_id):
        id = self.__unique_id(compiler_id)
        with self.__lock:
            assert id in self.__partial_compilers
            assert id not in self.__compilers
            assert os.path.exists(self.compiler_dir(compiler_id))
            self.__partial_compilers.remove(id)
            self.__compilers.add(id)
