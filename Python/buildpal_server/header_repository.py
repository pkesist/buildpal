from io import BytesIO, FileIO

import os
import shutil
import tempfile
import map_files

from collections import defaultdict
from threading import Lock
from hashlib import md5

class HeaderRepository:
    """
    Abstract base class for implementing header file repository.

    The purpose of the repository is to store headers, so that each session
    does not have to send its entire world. This class will eventually,
    given enough tasks, create a mirror of the Clients include paths.
    """
    def __init__(self, scratch_dir):
        self.scratch_dir = scratch_dir
        self.checksums = defaultdict(dict)
        self.locks = defaultdict(Lock)
        self.dir = os.path.join(scratch_dir, 'Headers')
        os.makedirs(self.dir, exist_ok=True)
        self.session_lock = Lock()
        self.session_data = {}
        self.tempdirs = {}

    def create_temp_file(self, session_id, remote_dir, name, content):
        """
        Create a temporary header, which will be needed for one session only.
        """
        raise NotImplementedError()

    def create_shared_file(self, machine_id, remote_dir, name, content):
        """
        Create a shared header file, i.e. one which is saved and used by
        multiple sessions.
        """
        raise NotImplementedError()

    def missing_files(self, machine_id, session_id, in_list):
        """
        Given a machine identification and a list of header files,
        return a 2-tuple, list of files which are missing, and a
        session unique identifier which will be passed to
        prepare_dir() together with the missing files.
        """
        needed_files = {}
        out_list = set()
        dirs = set()
        for remote_dir, data in in_list:
            dirs.add(remote_dir)
            for name, checksum in data:
                key = (remote_dir, name)
                if self.checksums[machine_id].get(key) != checksum:
                    needed_files[key] = checksum
                    out_list.add(key)
        with self.session_lock:
            self.session_data[session_id] = needed_files, dirs
        return out_list

    def tempdir(self, session_id):
        return self.tempdirs[session_id]

    def prepare_dir(self, machine_id, session_id, new_files):
        """
        We received files which we reported missing.
        """
        with self.session_lock:
            needed_files, tmp_include_paths = self.session_data[session_id]
        del self.session_data[session_id]

        checksums = self.checksums[machine_id]

        sandbox_dir = tempfile.mkdtemp(dir=self.scratch_dir)
        self.tempdirs[session_id] = sandbox_dir

        include_paths = [sandbox_dir]
        include_paths.extend(tmp_include_paths)

        temp_files = []
        # Update headers.
        for (remote_dir, name), content in new_files.items():
            shared = (remote_dir, name) in needed_files
            if shared:
                checksum = needed_files[(remote_dir, name)]
                self.create_shared(machine_id, session_id, remote_dir, name, checksum, content)
            else:
                temp_files.append((remote_dir, name, content))
                # If not a part of needed_files, extract it directly to
                # sandbox_dir and do not store it.
        src_file = self.process_temp_files(session_id, temp_files)
        return include_paths, src_file

    def create_shared(self, machine_id, session_id, remote_dir, name, checksum, content):
        create_shared = False
        create_local = False
        key = (remote_dir, name)
        lock = self.locks[machine_id]
        checksums = self.checksums[machine_id]
        with lock:
            old_checksum = checksums.get(key)
            if old_checksum is None:
                checksums[key] = 'IN_PROGRESS'
                create_shared = True
            else:
                create_local = old_checksum != checksum
        if create_local:
            self.create_temp_file(session_id, remote_dir, name, content)
        if create_shared:
            self.create_shared_file(machine_id, remote_dir, name, content)
            with lock:
                checksums[key] = checksum

    def source_file(self, session_id, cwd, src_loc):
        raise NotImplementedError()

    def session_complete(self, session_id):
        if session_id in self.tempdirs:
            try:
                shutil.rmtree(self.tempdirs[session_id])
            except PermissionError:
                pass
            finally:
                del self.tempdirs[session_id]

    def get_mappings(self, machine_id, session_id):
        return []

class MapFiles(HeaderRepository):
    """
    A HeaderRepository implementation based on map_files module.
   
    This implementation makes headers available on the same path as on
    the client machine.
    """
    def __init__(self, scratch_dir):
        super().__init__(scratch_dir)
        self.global_map = defaultdict(map_files.FileMap)
        self.temp_map = defaultdict(map_files.FileMap)

    def _create_virtual_file(self, dir, file_map, virtual_file, content):
        handle, real_file = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as file:
            file.write(content)
        file_map.map_file(virtual_file, real_file)

    def create_temp_file(self, session_id, remote_dir, name, content):
        tmpdir = self.tempdirs[session_id]
        self._create_virtual_file(tmpdir, self.temp_map[session_id],
            os.path.join(remote_dir, name), content)

    def create_shared_file(self, machine_id, remote_dir, name, content):
        self._create_virtual_file(self.dir, self.global_map[machine_id],
            os.path.join(remote_dir, name), content)

    def process_temp_files(self, session_id, temp_files):
        src_file = None
        for remote_dir, name, content in temp_files:
            if not remote_dir:
                tmpdir = self.tempdirs[session_id]
                self._create_virtual_file(tmpdir, self.temp_map[session_id],
                    name, content)
                src_file = name
            else:
                self.create_temp_file(session_id, remote_dir, name, content)
        return src_file

    def session_complete(self, session_id):
        self.temp_map.pop(session_id, None)
        super().session_complete(session_id)

    def get_mappings(self, machine_id, session_id):
        return [self.global_map[machine_id], self.temp_map[session_id]]

    def source_file(self, session_id, cwd, src_loc):
        return os.path.join(cwd, src_loc)


class MapIncludeDirs(HeaderRepository):
    """
    A HeaderRepository implementation which maps client include paths into
    temporary directories.
    """
    def __init__(self, scratch_dir):
        super().__init__(scratch_dir)
        self.dir_map = defaultdict(dict)

    def map_dir(self, machine_id, dir):
        result = self.dir_map[machine_id].get(dir)
        if not result:
            hash = md5(machine_id.encode())
            hash.update(dir.encode())
            result = os.path.join(self.dir, hash.hexdigest())
            self.dir_map[machine_id][dir] = result
        return result

    @staticmethod
    def header_heading(filename):
        """
        This heading is placed at the beginning of each source and header to
        make the compiler generate debug symbols with correct (client) paths.

        Unfortunately, this will break #pragma once on MSVC 11.0 and possibly
        others due to compiler bug.

        TODO: Use only on MSVC, and only on versions which work (9.0)
        """
        # 'sourceannotations.h' header is funny. If you add a #line directive to
        # it it will start tossing incomprehensible compiler erros. It would
        # seem that cl.exe has some hardcoded logic for this header. Person
        # responsible for this should be severely punished.
        if 'sourceannotations.h' in filename:
            return b''
        # Unfortunately, #line will render #pragma once useless on MSVC 11.0
        # (possibly others) due to compiler bug. Works with 9.0.
        pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
        return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

    @staticmethod
    def create_file_in_dir(dir, name, realname, content):
        filename = os.path.normpath(os.path.join(dir, name))
        upperdirs = os.path.dirname(filename)
        if upperdirs and not os.path.exists(upperdirs):
            os.makedirs(upperdirs, exist_ok=True)
        with open(filename, 'wb') as file:
            file.write(MapIncludeDirs.header_heading(realname))
            file.write(content)

    def create_temp_file(self, session_id, remote_dir, name, content):
        temp_dir = self.tempdirs[session_id]
        return MapIncludeDirs.create_file_in_dir(temp_dir, name, os.path.join(
            remote_dir, name), content)

    def create_shared_file(self, machine_id, remote_dir, name, content):
        shared_dir = self.map_dir(machine_id, remote_dir)
        return MapIncludeDirs.create_file_in_dir(shared_dir, name, os.path.join(
            remote_dir, name), content)

    def process_temp_files(self, session_id, temp_files):
        relative_includes = {}
        rel_counter = 0
        max_depth = 0

        src_file = None
        src_content = None
        for remote_dir, name, content in temp_files:
            if not remote_dir:
                src_file, src_content = name, content
                continue
            name = os.path.normpath(name)
            path_elements = name.split(os.path.sep)
            # Handle '..' in include directive.
            depth = 0
            while path_elements[0] == '..':
                depth += 1
                if depth > max_depth:
                    max_depth = depth
                del path_elements[0]
            if depth:
                relative_includes.setdefault(depth - 1, []).append((remote_dir,
                    '/'.join(path_elements), content))
            else:
                self.create_temp_file(session_id, remote_dir, name, content)

        tempdir = self.tempdirs[session_id]
        curr_dir = ''
        for depth in range(max_depth):
            for remote_dir, file, content in relative_includes[depth]:
                MapIncludeDirs.create_file_in_dir(tempdir, file, os.path.join(
                    remote_dir, file), content)
            curr_dir = os.path.join(curr_dir, 'dummy_rel')
        short_src_file = os.path.join(curr_dir, os.path.basename(src_file))
        MapIncludeDirs.create_file_in_dir(self.tempdirs[session_id],
            short_src_file, src_file, src_content)
        return short_src_file


