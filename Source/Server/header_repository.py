from io import BytesIO

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
        for dir, name, relative, checksum, size in in_list:
            key = (dir, name)
            dirs.add(self.map_dir(dir))
            if key not in checksums or checksums[key] != checksum:
                needed_files[name] = dir, name, checksum, relative
                out_list.append(name)
        self.counter += 1
        self.session_data[self.counter] = needed_files, dirs
        return out_list, self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, local_dir):
        assert id in self.session_data
        include_paths = [local_dir]
        needed_files, include_dirs = self.session_data[id]
        include_paths.extend(include_dirs)
        del self.session_data[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)

        checksums, lock = self.checksums.get(machine_id)

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
                    new_files_tar.extract(tar_info, local_dir)
                else:
                    remote_dir, remote_name, checksum, relative = needed_files[tar_info.name]
                    if relative:
                        new_files_tar.extract(tar_info, local_dir)
                    else:
                        content = new_files_tar.extractfile(tar_info)
                        shared_dir = self.map_dir(remote_dir)
                        filename = os.path.join(shared_dir, remote_name)

                        def create_file_in_dir(dir):
                            filename = os.path.normpath(os.path.join(dir, remote_name))
                            os.makedirs(os.path.dirname(filename), exist_ok=True)
                            with open(filename, 'wb') as file:
                                file.write(content.read())

                        # Try to avoid lock.
                        if (remote_dir, remote_name) in checksums:
                            # Someone created this file in the meantime.
                            # We will use our own copy.
                            create_file_in_dir(local_dir)
                        else:
                            # Try to place this file in the shared dir.
                            with lock:
                                # See if this entry was added while we were taking lock.
                                exists = (remote_dir, remote_name) in checksums
                                if not exists:
                                    checksums[(remote_dir, remote_name)] = checksum
                            create_file_in_dir(local_dir if exists else shared_dir)
                        if not shared_dir in include_paths:
                            include_paths.append(shared_dir)
        return include_paths
