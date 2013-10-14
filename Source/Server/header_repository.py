from io import BytesIO

import os
import shutil
import tempfile
import tarfile
from threading import Lock

class Header:
    def __init__(self, abs, mtime, dir, reader):
        self._abs = abs
        self._mtime = mtime
        handle, self.filename = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as tmp:
            for data in iter(reader.read, b''):
                tmp.write(data)
            self._size = tmp.tell()

    def matches(self, tar_info):
        return tar_info.mtime == self._mtime and \
            tar_info.size == self._size

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
        self.filelists = {}

    def missing_files(self, machine_id, in_tar_buffer):
        in_tar_stream = BytesIO(in_tar_buffer)
        out_tar_stream = BytesIO()
        filelist = {}
        with tarfile.open(mode='r', fileobj=in_tar_stream) as in_tar, \
            tarfile.open(mode='w', fileobj=out_tar_stream) as out_tar:
            files = list((tarinfo.linkname, tarinfo) for tarinfo in in_tar)
            machine_files = self.files.get(machine_id)
            for abs, tar_info in files:
                filelist[tar_info.name] = tar_info
                if abs not in machine_files or \
                    not machine_files[abs].matches(tar_info):
                    out_tar.addfile(tar_info)
        out_tar_stream.seek(0)
        self.counter += 1
        self.filelists[self.counter] = filelist
        return out_tar_stream.read(), self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, dir):
        assert id in self.filelists
        filelist = self.filelists[id]
        del self.filelists[id]
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
                elif not tar_info.name in filelist:
                    # If not a part of filelist, extract it directly to dir and
                    # do not remember it.
                    new_files_tar.extract(tar_info, dir)
                else:
                    fl_tar_info = filelist[tar_info.name]
                    content = new_files_tar.extractfile(tar_info)
                    original_name = fl_tar_info.linkname
                    machine_files[original_name] = Header(original_name,
                        fl_tar_info.mtime, self.dir, content)
            # Do not copy the files here. This is a shared resource and we want
            # to be as fast as possible. Let the caller worry about copying.
            files_to_copy = list(
                (machine_files[tar_info.linkname].location(), tar_info.name)
                for tar_info in filelist.values() if tar_info.linkname in
                machine_files)
        return include_paths, files_to_copy
