from io import BytesIO

import os
import shutil
import tempfile
import tarfile
from threading import Lock

class Header:
    def __init__(self, abs, mtime, name, dir, reader):
        self._name = name
        self._abs = abs
        self._mtime = mtime
        handle, self.filename = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as tmp:
            for data in iter(reader.read, b''):
                tmp.write(data)
            self._size = tmp.tell()

    def matches(self, tar_info):
        result = tar_info.linkname == self._abs and \
            tar_info.mtime == self._mtime and \
            tar_info.size == self._size
        if not result:
            print("NO MATCH")
            print(tar_info.linkname, self._abs)
            print(tar_info.mtime, self._mtime)
            print(tar_info.size, self._size)

    def size(self):
        return self._size

    def name(self):
        return self._name

    def location(self):
        return self.filename

class FileList:
    def __init__(self):
        self.files = {}

    def get(self, machine):
        self.files.setdefault(machine, {})
        return self.files[machine]

    def required(self, machine, tar_info):
        return tar_info.name not in self.get(machine) or \
            not self.files[machine][tar_info.name].matches(tar_info)

    def override(self, machine, name, header):
        assert machine in self.files
        self.files[machine][name] = header


class HeaderRepository:
    def __init__(self):
        self.files = FileList()
        self.dir = tempfile.mkdtemp()
        self.make_header_lock = Lock()
        self.counter = 0
        self.filelists = {}

    def missing_files(self, machine_id, in_tar_buffer):
        in_tar_stream = BytesIO(in_tar_buffer)
        out_tar_stream = BytesIO()
        with tarfile.open(mode='r', fileobj=in_tar_stream) as in_tar, \
            tarfile.open(mode='w', fileobj=out_tar_stream) as out_tar:
            for tar_info in in_tar.getmembers():
                if self.files.required(machine_id, tar_info):
                    out_tar.addfile(tar_info)
        out_tar_stream.seek(0)
        self.counter += 1
        self.filelists[self.counter] = in_tar_buffer
        return out_tar_stream.read(), self.counter

    def prepare_dir(self, machine_id, new_files_tar_buffer, id, dir):
        assert id in self.filelists
        filelist_tar_buffer = self.filelists[id]
        del self.filelists[id]
        new_files_tar_stream = BytesIO(new_files_tar_buffer)
        filelist_tar_stream = BytesIO(filelist_tar_buffer)

        # Update headers.
        with tarfile.open(mode='r', fileobj=new_files_tar_stream) as new_files_tar, \
            tarfile.open(mode='r', fileobj=filelist_tar_stream) as filelist_tar:

            filelist = dict((tar_info.name, tar_info) for tar_info in filelist_tar.getmembers())

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
                    with self.make_header_lock:
                        fl_tar_info = filelist[tar_info.name]
                        content = new_files_tar.extractfile(tar_info)
                        self.files.override(machine_id, tar_info.name, Header(
                            fl_tar_info.linkname, fl_tar_info.mtime, fl_tar_info.name,
                            self.dir, content))
            # Do not copy the files here. This is a shared resource and we want
            # to be as fast as possible. Let the caller worry about copying.
            files_to_copy = list((self.files.get(machine_id)[tar_info.name].location(), tar_info.name)
                                 for tar_info in filelist.values()
                                 if tar_info.name in self.files.get(machine_id))
        return include_paths, files_to_copy
        
