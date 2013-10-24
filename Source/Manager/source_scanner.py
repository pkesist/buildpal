from .scan_headers import collect_headers

from Common import SimpleTimer, write_str_to_tar

import zmq
import tarfile
import os
import pickle
from hashlib import md5

from io import BytesIO
from multiprocessing import Process

class SourceScanner(Process):
    def __init__(self, port, nodes):
        self.__port = port
        self.__nodes = nodes
        return super().__init__()

    class Session:
        STATE_ATTACHING_TO_SESSION = 0
        STATE_SENDING_FILE_LIST = 1

        def __init__(self, task, header_info, time, node_index):
            self.state = self.STATE_ATTACHING_TO_SESSION
            self.task = task
            self.header_info = header_info
            self.filelist = self.create_filelist()
            self.time = time
            self.node_index = node_index

        def create_filelist(self):
            filelist = []
            for file, abs, content, header, digest in self.header_info:
                filelist.append((file, digest, len(content) + len(header), os.path.normpath(abs)))
            return filelist

    def run(self):
        zmq_ctx = zmq.Context()
        mgr_socket = zmq_ctx.socket(zmq.DEALER)
        mgr_socket.connect('tcp://localhost:{}'.format(self.__port))
        sockets = {}
        sessions = {}

        poller = zmq.Poller()
        poller.register(mgr_socket, zmq.POLLIN)

        while True:
            socks = dict(poller.poll())
            for sock, event in socks.items():
                assert event == zmq.POLLIN
                if sock is mgr_socket:
                    server_id, task, node_index = mgr_socket.recv_multipart()
                    task = pickle.loads(task)
                    node_index = pickle.loads(node_index)
                    timer = SimpleTimer()
                    header_info = list(self.header_info(task))
                    time = timer.get()

                    available_sockets = sockets.setdefault(node_index, [])
                    if available_sockets:
                        socket = available_sockets[0]
                        del available_sockets[0]
                    else:
                        socket = zmq_ctx.socket(zmq.DEALER)
                        socket.connect(self.__nodes[node_index]['address'])
                    socket.send_multipart([b'ATTACH_TO_SESSION', server_id])
                    poller.register(socket, zmq.POLLIN)
                    sessions[socket] = self.Session(task, header_info, time, node_index)
                else:
                    assert sock in sessions
                    session = sessions[sock]
                    if session.state == self.Session.STATE_ATTACHING_TO_SESSION:
                        msg = sock.recv_multipart()
                        assert len(msg) == 1 and msg[0] == b'SESSION_ATTACHED'
                        sock.send_multipart([b'TASK_FILE_LIST', pickle.dumps(session.filelist), pickle.dumps(session.time)])
                        session.state = self.Session.STATE_SENDING_FILE_LIST
                    elif session.state == self.Session.STATE_SENDING_FILE_LIST:
                        resp = sock.recv_multipart()
                        assert len(resp) == 2 and resp[0] == b'MISSING_FILES'
                        req_files = pickle.loads(resp[1])
                        new_tar = self.tar_with_new_headers(session.task, req_files, session.header_info)
                        sock.send_multipart([b'TASK_FILES', new_tar.read()])
                        poller.unregister(sock)
                        node_index = session.node_index
                        del sessions[sock]
                        sockets[node_index].append(sock)
                    else:
                        assert not "Invalid state"

    @classmethod
    def header_beginning(cls, filename):
        pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
        return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

    @classmethod
    def tar_with_new_headers(cls, task, in_filelist, header_info):
        paths_to_include = []
        relative_paths = {}
        tar_buffer = BytesIO()
        rel_counter = 0
        with tarfile.open(mode='w', fileobj=tar_buffer) as out_tar:
            header_info_iter = iter(header_info)
            for in_name in in_filelist:
                found = False
                while not found:
                    try:
                        file, abs, content, header, digest = next(header_info_iter)
                        if in_name == file:
                            found = True
                            break
                    except StopIteration:
                        print("Could not find information for", in_name)
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
                write_str_to_tar(out_tar, rel_file, src.read(), cls.header_beginning(cpp_file))
        tar_buffer.seek(0)
        return tar_buffer

    @classmethod
    def header_info(cls, task):
        header_info = collect_headers(task['cwd'], task['source'],
            task['includes'], task['sysincludes'], task['macros'],
            [task['pch_header']] if task['pch_header'] else [])
        for file, abs, content in header_info:
            input = BytesIO(content)
            hash = md5()
            for chunk in iter(lambda : input.read(128 * hash.block_size), b''):
                hash.update(chunk)
            digest = hash.digest()
            yield file, abs, content, cls.header_beginning(abs), digest
