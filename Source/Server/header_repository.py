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
        self.dir_lock = {}
        self.dir_map = {}

    def lock_dir(self, dir):
        assert dir in self.dir_map
        result = self.dir_lock.get(dir)
        if not result:
            result = Lock()
            self.dir_lock[dir] = result
        return result

    def map_dir(self, dir):
        result = self.dir_map.get(dir)
        if not result:
            result = os.path.join(self.dir, md5(dir.encode()).hexdigest())
            self.dir_map[dir] = result
        return result

    def missing_files(self, machine_id, in_list):
        needed_files = {}
        out_list = []
        checksums = self.checksums.setdefault(machine_id, {})
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

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, dir):
        assert id in self.session_data
        include_paths = [dir]
        needed_files, include_dirs = self.session_data[id]
        include_paths.extend(include_dirs)
        del self.session_data[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)

        checksums = self.checksums.get(machine_id)

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
                    remote_dir, remote_name, checksum, relative = needed_files[tar_info.name]
                    if relative:
                        new_files_tar.extract(tar_info, dir)
                    else:
                        content = new_files_tar.extractfile(tar_info)
                        # Extract system files to a fixed location which can be
                        # reused.
                        dirname = self.map_dir(remote_dir)
                        filename = os.path.join(dirname, remote_name)
                        try:
                            # Try to place the file in the shared dir.
                            os.makedirs(os.path.dirname(filename), exist_ok=True)
                            with open(filename, 'wb') as file:
                                file.write(content.read())
                            checksums[(remote_dir, remote_name)] = checksum
                        except Exception:
                            # If that fails for any reason - unpack to compiler
                            # process specific dir.
                            # TODO: This will fail in case this header is
                            # included from another header via relative path.
                            filename = os.path.normpath(os.path.join(dir, remote_name))
                            os.makedirs(os.path.dirname(filename), exist_ok=True)
                            with open(filename, 'wb') as file:
                                file.write(content.read())
                        if not dirname in include_paths:
                            include_paths.append(dirname)
        return include_paths
