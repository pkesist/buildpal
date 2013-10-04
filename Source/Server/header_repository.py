from io import BytesIO
import os

import tarfile

class Header:
    def __init__(self, name, content):
        self.name = name
        self.content = content

    def size(self):
        return len(self.content)

    def name(self):
        return self.name

    def write_to_dir(self, dirname):
        full_name = os.path.join(dirname, self.name)
        try:
            with open(full_name, 'wb') as file:
                file.write(self.content)
        except FileNotFoundError:
            # Probably a missing directory.
            folder, file = os.path.split(full_name)
            os.makedirs(folder, exist_ok=True)
            with open(full_name, 'wb') as file:
                file.write(self.content)

class HeaderRepository:
    def __init__(self):
        self.headers = {}

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
                    self.headers[tar_info.name] = Header(tar_info.name, content.read(-1))

            include_paths = [dir]
            for tar_info in filelist:
                assert tar_info.name in self.headers
                assert tar_info.size == self.headers[tar_info.name].size()
                self.headers[tar_info.name].write_to_dir(dir)
        return include_paths
        
