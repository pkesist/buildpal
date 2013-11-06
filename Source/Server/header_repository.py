from io import BytesIO

import os
import shutil
import tempfile
import tarfile
from threading import Lock

class Header:
    def __init__(self, abs, checksum, dir, reader):
        self._abs = abs
        self._checksum = checksum
        handle, self.filename = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as tmp:
            for data in iter(reader.read, b''):
                tmp.write(data)
            self._size = tmp.tell()

    def matches(self, size, checksum):
        return size == self._size and self._checksum == checksum

    def size(self):
        return self._size

    def location(self):
        return self.filename

class FileList:
    def __init__(self):
        self.files = {}

    def get(self, machine):
        return self.files.setdefault(machine, {})

class HeaderRepository:
    def __init__(self):
        self.files = FileList()
        self.dir = tempfile.mkdtemp()
        self.counter = 0
        self.needed_files = {}

    def missing_files(self, machine_id, in_list):
        needed_files = {}
        out_list = []
        machine_files = self.files.get(machine_id)
        for name, checksum, size, abs in in_list:
            needed_files[name] = abs, checksum
            if abs not in machine_files or \
                not machine_files[abs].matches(size, checksum):
                out_list.append(name)
        self.counter += 1
        self.needed_files[self.counter] = needed_files
        return out_list, self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, dir):
        assert id in self.needed_files
        needed_files = self.needed_files[id]
        del self.needed_files[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)

        machine_files = self.files.get(machine_id)

        # Update headers.
        with tarfile.open(mode='r', fileobj=new_files_tar_stream) as new_files_tar:
            include_paths = [dir]
            for tar_info in new_files_tar.getmembers():
                if tar_info.name == 'include_paths.txt':
                    include_dir_reader = new_files_tar.extractfile(tar_info)
                    include_dirs = include_dir_reader.read().split(b'\n')
                    for include_dir in include_dirs:
                        assert not os.path.isabs(include_dir)
                        include_paths.append(
                            os.path.normpath(os.path.join(dir,
                                                          include_dir.decode())))
                elif not tar_info.name in needed_files:
                    # If not a part of needed_files, extract it directly to dir
                    # and do not remember it.
                    new_files_tar.extract(tar_info, dir)
                else:
                    abs, checksum = needed_files[tar_info.name]
                    content = new_files_tar.extractfile(tar_info)
                    machine_files[abs] = Header(abs, checksum, self.dir, content)
            # Do not copy the files here. This is a shared resource and we want
            # to be as fast as possible. Let the caller worry about copying.
            files_to_copy = list((machine_files[abs].location(), name, checksum)
                for name, (abs, checksum) in needed_files.items())
        return include_paths, files_to_copy
