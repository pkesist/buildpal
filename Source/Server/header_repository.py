from io import BytesIO

import os
import shutil
import tempfile
import tarfile

class Header:
    def __init__(self, name, dir, reader):
        self._name = name
        handle, self.filename = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as tmp:
            for data in iter(reader.read, b''):
                tmp.write(data)
            self._size = tmp.tell()

    def size(self):
        return self._size

    def name(self):
        return self._name

    def location(self):
        return self.filename

class HeaderRepository:
    def __init__(self):
        self.headers = {}
        self.dir = tempfile.mkdtemp()

    def missing_files(self, in_tar_buffer):
        in_tar_stream = BytesIO(in_tar_buffer)
        out_tar_stream = BytesIO()
        with tarfile.open(mode='r', fileobj=in_tar_stream) as in_tar, \
            tarfile.open(mode='w', fileobj=out_tar_stream) as out_tar:
            for tar_info in in_tar.getmembers():
                if tar_info.name not in self.headers or \
                    self.headers[tar_info.name].size() != tar_info.size:
                    out_tar.addfile(tar_info)
        out_tar_stream.seek(0)
        return out_tar_stream.read()

    def prepare_dir(self, new_files_tar_buffer, filelist_tar_buffer, dir):
        new_files_tar_stream = BytesIO(new_files_tar_buffer)
        filelist_tar_stream = BytesIO(filelist_tar_buffer)

        # Update headers.
        with tarfile.open(mode='r', fileobj=new_files_tar_stream) as new_files_tar, \
            tarfile.open(mode='r', fileobj=filelist_tar_stream) as filelist_tar:

            filelist = filelist_tar.getmembers()
            filenames = list(tar_info.name for tar_info in filelist)

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
                elif not tar_info.name in filenames:
                    # If not a part of filelist, extract it directly to dir and
                    # do not remember it.
                    new_files_tar.extract(tar_info, dir)
                else:
                    content = new_files_tar.extractfile(tar_info)
                    try:
                        self.headers[tar_info.name] = Header(tar_info.name, self.dir, content)
                    except:
                        import traceback
                        traceback.print_exc()
                        raise
            # Do not copy the files here. This is a shared resource and we want
            # to be as fast as possible. Let the caller worry about copying.
            files_to_copy = list((self.headers[tar_info.name].location(), tar_info.name)
                                 for tar_info in filelist if tar_info.name in self.headers)
        return include_paths, files_to_copy
        
