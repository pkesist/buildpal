import os

from collections import defaultdict
from hashlib import md5

class PCHRepository:
    def __init__(self, scratch_dir):
        self.__dir = dir=os.path.join(scratch_dir, 'PCH')
        os.makedirs(self.__dir, exist_ok=True)
        self.__files = {}
        self.__partial_files = {}
        self.__waiters = defaultdict(list)

    def register_file(self, pch_file):
        if pch_file in self.__files:
            return self.__files[pch_file], False
        if pch_file in self.__partial_files:
            return self.__partial_files[pch_file], False
        dir, fn = os.path.split(pch_file[0])
        local_filename = os.path.join(self.__dir, md5(dir.encode()).hexdigest(), fn)
        os.makedirs(os.path.dirname(local_filename), exist_ok=True)
        self.__partial_files[pch_file] = local_filename
        return local_filename, True

    def when_pch_is_available(self, pch_file, handler):
        if pch_file in self.__files:
            handler()
        else:
            self.__waiters[pch_file].append(handler)

    def file_completed(self, pch_file):
        self.__files[pch_file] = self.__partial_files[pch_file]
        del self.__partial_files[pch_file]
        for handler in self.__waiters[pch_file]:
            handler()
        del self.__waiters[pch_file]
