import os
import tempfile

from threading import Lock
from shutil import rmtree

class FileRepository:
    def __init__(self):
        self.__dir = tempfile.mkdtemp()
        self.__lock = Lock()
        self.__files = {}
        self.__partial_files = {}

    def __del__(self):
        try:
            rmtree(self.__dir)
            os.rmdir(self.__dir)
        except Exception:
            pass

    def register_file(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            if key in self.__files:
                return self.__files[key], False
            if key in self.__partial_files:
                return self.__partial_files[key], False
            ext = os.path.splitext(filename)[1]
            handle, local_filename = tempfile.mkstemp(dir=self.__dir, suffix=ext)
            os.close(handle)
            self.__partial_files[key] = local_filename
            return local_filename, True

    def file_arrived(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            return key in self.__files

    def file_completed(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            self.__files[key] = self.__partial_files[key]
            del self.__partial_files[key]
