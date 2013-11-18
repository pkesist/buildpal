import os
import tempfile

from threading import Lock
from shutil import rmtree
from hashlib import md5

class FileRepository:
    def __init__(self):
        self.__dir=os.path.join(tempfile.gettempdir(), "DistriBuild", "PCH")
        os.makedirs(self.__dir, exist_ok=True)
        self.__lock = Lock()
        self.__files = {}
        self.__partial_files = {}

    def register_file(self, filename, size, last_modified):
        key = (filename, size, last_modified)
        with self.__lock:
            if key in self.__files:
                return self.__files[key], False
            if key in self.__partial_files:
                return self.__partial_files[key], False
            dir, fn = os.path.split(filename)
            local_filename = os.path.join(self.__dir, md5(dir.encode()).hexdigest(), fn)
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
