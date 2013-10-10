from .scan_headers import collect_headers

from Common import SimpleTimer, write_str_to_tar

import zmq
import tarfile
import os
import pickle

from io import BytesIO
from multiprocessing import Process

class SourceScanner(Process):
    def __init__(self, port, timer, nodes):
        self.__port = port
        self.__timer = timer
        self.__nodes = nodes
        return super().__init__()

    def run(self):
        zmq_ctx = zmq.Context()
        mgr_socket = zmq_ctx.socket(zmq.DEALER)
        mgr_socket.connect('tcp://localhost:{}'.format(self.__port))
        sockets = {}

        while True:
            server_id, task, node_index = mgr_socket.recv_multipart()
            task = pickle.loads(task)
            node_index = pickle.loads(node_index)
            timer = SimpleTimer()
            header_info = self.header_info(task)
            header_info = list(h + (self.header_beginning(h[1]),) for h in header_info)
            tar_with_filelist = self.tar_with_filelist(header_info)

            socket = sockets.get(node_index)
            if not socket:
                socket = zmq_ctx.socket(zmq.DEALER)
                socket.connect(self.__nodes[node_index]['address'])
                sockets[node_index] = socket

            socket.send_multipart([b'ATTACH_TO_SESSION', server_id])
            msg = socket.recv_multipart()
            assert len(msg) == 1 and msg[0] == b'SESSION_ATTACHED'

            socket.send_multipart([b'TASK_FILE_LIST', tar_with_filelist.read(), pickle.dumps(timer.get())])
            resp = socket.recv_multipart()
            assert len(resp) == 2 and resp[0] == b'MISSING_FILES'
            req_tar = BytesIO(resp[1])

            new_tar = self.tar_with_new_headers(task, req_tar, header_info)
            socket.send_multipart([b'TASK_FILES', new_tar.read()])

    def tar_with_filelist(self, header_info):
        tar_buffer = BytesIO()
        with tarfile.open(mode='w', fileobj=tar_buffer) as tar:
            for file, abs, content, header in header_info:
                tar_info = tarfile.TarInfo()
                tar_info.name = file
                stat = os.stat(abs)
                tar_info.size = stat.st_size + len(header)
                tar_info.mtime = stat.st_mtime
                tar_info.type = tarfile.SYMTYPE
                tar_info.linkname = os.path.normpath(abs)
                tar.addfile(tar_info)
        tar_buffer.seek(0)
        return tar_buffer

    @classmethod
    def header_beginning(cls, filename):
        pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
        return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

    def tar_with_new_headers(self, task, tar_with_filelist, header_info):
        paths_to_include = []
        relative_paths = {}
        tar_buffer = BytesIO()
        rel_counter = 0
        with tarfile.open(mode='r', fileobj=tar_with_filelist) as in_tar, \
            tarfile.open(mode='w', fileobj=tar_buffer) as out_tar:
            header_info_iter = iter(header_info)
            for tar_info in in_tar.getmembers():
                found = False
                while not found:
                    try:
                        file, abs, content, header = next(header_info_iter)
                        if file == tar_info.name:
                            found = True
                            break
                    except StopIteration:
                        print("Could not find information for", tar_info.name)
                        raise
                assert found
                depth = 0
                path_elements = file.split('/')
                # Handle '.' in include directive.
                path_elements = [p for p in path_elements if p != '.']
                # Handle '..' in include directive.
                while '..' in path_elements:
                    index = path_elements.index('..')
                    if index == 0:
                        depth += 1
                        del path_elements[index]
                    else:
                        del path_element[index - 1:index + 1]
                if depth:
                    path_elements = ['_rel_includes'] + path_elements
                    if not depth in relative_paths:
                        # Add a dummy file which will create this structure.
                        relative_paths[depth] = '_rel_includes/' + 'rel/' * depth
                        paths_to_include.append(relative_paths[depth])
                        write_str_to_tar(out_tar, relative_paths[depth] + 'dummy', b'')
                write_str_to_tar(out_tar, '/'.join(path_elements), content, header)
            if paths_to_include:
                write_str_to_tar(out_tar, 'include_paths.txt', "\n".join(paths_to_include).encode())
            rel_file = task['source']
            cpp_file = os.path.join(task['cwd'], rel_file)
            with open(cpp_file, 'rb') as src:
                write_str_to_tar(out_tar, rel_file, src.read(), self.header_beginning(cpp_file))
        tar_buffer.seek(0)
        return tar_buffer

    def header_info(self, task):
        # FIXME: This does not belong here. Move this to msvc.py.
        # We would like to avoid scanning system headers here if possible.
        # If we do so, we lose any preprocessor side-effects. We try to
        # hardcode this knowledge here.
        macros = task['macros']
        if '_DEBUG' in macros:
            if not any(('_SECURE_SCL' in x for x in macros)):
                macros.append('_SECURE_SCL=1')
            if not any(('_HAS_ITERATOR_DEBUGGING' in x for x in macros)):
                macros.append('_HAS_ITERATOR_DEBUGGING=1')
        # FIXME:
        # Usually we don't need sysincludes and including them is really slow.
        # See what to do about this.
        task['sysincludes'] = []

        return collect_headers(task['cwd'], task['source'],
            task['includes'], task['sysincludes'], macros,
            [task['pch_header']] if task['pch_header'] else [])
