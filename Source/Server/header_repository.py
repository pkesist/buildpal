from io import BytesIO

import os
import shutil
import tempfile
import tarfile
from threading import Lock
from hashlib import md5

class Header:
    def __init__(self, src_dir, src_file, checksum, fileobj, filename, reader, dir):
        self._checksum = checksum
        self._filename = filename
        self._dir = dir
        for data in iter(reader.read, b''):
            fileobj.write(data)
        self._size = fileobj.tell()

    def matches(self, size, checksum):
        return size == self._size and self._checksum == checksum

    def size(self):
        return self._size

    def location(self):
        return self._filename

    def dir(self):
        return self._dir

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
        self.session_data = {}
        self.system_dir_lock = Lock()
        self.dir_map = {}

    def map_dir(self, dir):
        result = self.dir_map.get(dir)
        if not result:
            result = os.path.join(self.dir, md5(dir.encode()).hexdigest())
            self.dir_map[dir] = result
        return result

    def missing_files(self, machine_id, in_list):
        needed_files = {}
        out_list = []
        machine_files = self.files.get(machine_id)
        dirs = set()
        for dir, name, system, relative, checksum, size in in_list:
            needed_files[name] = dir, checksum, relative
            if (dir, name) not in machine_files or \
                not machine_files[(dir, name)].matches(size, checksum):
                out_list.append(name)
            else:
                dirs.add(self.map_dir(dir))

        self.counter += 1
        self.session_data[self.counter] = needed_files, dirs
        return out_list, self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, dir):
        assert id in self.session_data
        include_paths = [dir]
        needed_files, include_dirs = self.session_data[id]
        include_paths.extend(include_dirs)
        del self.session_data[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)

        machine_files = self.files.get(machine_id)

        # Update headers.
        with tarfile.open(mode='r', fileobj=new_files_tar_stream) as new_files_tar:
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
                    remote_dir, checksum, relative = needed_files[tar_info.name]
                    if relative:
                        new_files_tar.extract(tar_info, dir)
                    else:
                        content = new_files_tar.extractfile(tar_info)
                        # Extract system files to a fixed location which can be
                        # reused.
                        name = os.path.normpath(tar_info.name).lower()
                        dirname = self.map_dir(remote_dir)
                        filename = os.path.join(dirname, name)
                        os.makedirs(os.path.dirname(filename), exist_ok=True)
                        with self.system_dir_lock:
                            if not os.path.exists(filename):
                                fileobj = open(filename, 'wb')
                                machine_files[(dir, name)] = Header(dir, name, checksum, fileobj, filename, content, dirname)
                        if not dirname in include_paths:
                            include_paths.append(dirname)
        return include_paths
