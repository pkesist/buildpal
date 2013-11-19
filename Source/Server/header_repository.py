from io import BytesIO, FileIO

import os
import shutil
import tempfile
import tarfile
from threading import Lock
from hashlib import md5

class HeaderRepository:
    def __init__(self):
        self.checksums = {}
        self.dir = os.path.join(tempfile.gettempdir(), 'DistriBuild', 'Headers')
        self.session_lock = Lock()
        self.counter = 0
        self.session_data = {}
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
        checksums, lock = self.checksums.setdefault(machine_id, ({}, Lock()))
        dirs = set()
        for dir, name, relative, checksum in in_list:
            key = (dir, name)
            dirs.add(self.map_dir(dir))
            if key not in checksums or checksums[key] != checksum:
                if not relative:
                    needed_files[name] = dir, name, checksum
                out_list.append(name)
        with self.session_lock:
            self.counter += 1
            self.session_data[self.counter] = needed_files, dirs
        return out_list, self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, local_dir):
        with self.session_lock:
            needed_files, include_dirs = self.session_data[id]
        include_paths = [local_dir]
        include_paths.extend(include_dirs)
        del self.session_data[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)

        checksums, lock = self.checksums.get(machine_id)

        def create_file_in_dir(dir, name, content):
            filename = os.path.normpath(os.path.join(dir, name))
            upperdirs = os.path.dirname(filename)
            if upperdirs and not os.path.exists(upperdirs):
                os.makedirs(upperdirs, exist_ok=True)
            # Do not inherit this handle.
            # This avoids a subprocess bug which is fixed in Python 3.4.
            fd = os.open(filename, os.O_CREAT | os.O_WRONLY | os.O_NOINHERIT)
            with os.fdopen(fd, 'wb') as file:
                file.write(content.read())

        # Update headers.
        with tarfile.open(mode='r', fileobj=new_files_tar_stream) as new_files_tar:
            for tar_info in new_files_tar.getmembers():
                if tar_info.name == 'include_paths.txt':
                    include_dir_reader = new_files_tar.extractfile(tar_info)
                    include_dirs = include_dir_reader.read().split(b'\n')
                    for include_dir in include_dirs:
                        assert not os.path.isabs(include_dir)
                        include_paths.append(
                            os.path.normpath(os.path.join(local_dir,
                                include_dir.decode())))
                elif not tar_info.name in needed_files:
                    # If not a part of needed_files, extract it directly to local_dir
                    # and do not remember it.
                    create_file_in_dir(local_dir, tar_info.name,
                        new_files_tar.extractfile(tar_info))
                else:
                    remote_dir, remote_name, checksum = needed_files[tar_info.name]
                    shared_dir = self.map_dir(remote_dir)
                    filename = os.path.join(shared_dir, remote_name)
                    create_shared = False
                    create_local = False
                    key = (remote_dir, remote_name)
                    with lock:
                        old_checksum = checksums.get(key)
                        if old_checksum is None:
                            checksums[key] = 'IN_PROGRESS'
                            create_shared = True
                        else:
                            create_local = old_checksum != checksum
                    content = new_files_tar.extractfile(tar_info)
                    if create_local:
                        create_file_in_dir(local_dir, remote_name, content)
                    if create_shared:
                        create_file_in_dir(shared_dir, remote_name, content)
                        with lock:
                            checksums[key] = checksum
        return include_paths
