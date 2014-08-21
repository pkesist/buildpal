import os
import shutil
import tempfile
import map_files

from collections import defaultdict
from threading import Lock

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

        self.global_map = defaultdict(map_files.FileMap)
        self.temp_map = defaultdict(map_files.FileMap)

    def create_temp_file(self, session_id, remote_dir, name, content):
        """
        Create a temporary header, which will be needed for one session only.
        """
        tmpdir = self.tempdirs[session_id]
        self._create_virtual_file(tmpdir, self.temp_map[session_id],
            os.path.join(remote_dir, name), content)

    def create_shared_file(self, machine_id, remote_dir, name, content):
        """
        Create a shared header file, i.e. one which is saved and used by
        multiple sessions.
        """
        self._create_virtual_file(self.dir, self.global_map[machine_id],
            os.path.join(remote_dir, name), content)

    def missing_files(self, machine_id, session_id, in_list):
        """
        Given a machine identification and a list of header files,
        return a 2-tuple, list of files which are missing, and a
        session unique identifier which will be passed to
        prepare_dir() together with the missing files.
        """
        needed_files = {}
        out_list = set()
        for remote_dir, data in in_list:
            for name, checksum in data:
                key = (remote_dir, name)
                if self.checksums[machine_id].get(key) != checksum:
                    needed_files[key] = checksum
                    out_list.add(key)
        with self.session_lock:
            self.session_data[session_id] = needed_files
        return out_list

    def prepare_dir(self, machine_id, session_id, new_files, includes):
        """
        We received files which we reported missing.
        """
        with self.session_lock:
            needed_files = self.session_data.pop(session_id)

        checksums = self.checksums[machine_id]
        sandbox_dir = self.tempdir(session_id)

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
        src_file = self._process_temp_files(session_id, temp_files)
        return includes, src_file

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

    def session_complete(self, session_id):
        self.temp_map.pop(session_id, None)
        if session_id in self.tempdirs:
            try:
                shutil.rmtree(self.tempdirs[session_id])
            except Exception:
                pass
            finally:
                del self.tempdirs[session_id]

    def get_mappings(self, machine_id, session_id):
        return [self.global_map[machine_id], self.temp_map[session_id]]

    def tempdir(self, session_id):
        return self.tempdirs.get(session_id) or self.tempdirs.setdefault(
            session_id, tempfile.mkdtemp(dir=self.scratch_dir))

    def _create_virtual_file(self, dir, file_map, virtual_file, content):
        handle, real_file = tempfile.mkstemp(dir=dir)
        with os.fdopen(handle, 'wb') as file:
            file.write(content)
        file_map.map_file(virtual_file, real_file)

    def _process_temp_files(self, session_id, temp_files):
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


