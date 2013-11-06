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
        STATE_ATTACHING_TO_SESSION = 1
        STATE_SENDING_FILE_LIST = 2

        def __init__(self, task, header_info, node_index):
            self.state = self.STATE_ATTACHING_TO_SESSION
            self.task = task
            self.header_info = header_info
            self.filelist = self.create_filelist()
            self.node_index = node_index

        def create_filelist(self):
            filelist = []
            for file, abs, system, content, header, digest in self.header_info:
                filelist.append((file, digest, len(content) + len(header), os.path.normpath(abs)))
            return filelist

    STATE_WAITING_FOR_TASK = 0
    STATE_WAITING_FOR_SERVER = 1

    def run(self):
        zmq_ctx = zmq.Context()
        mgr_socket = zmq_ctx.socket(zmq.DEALER)
        mgr_socket.connect('tcp://localhost:{}'.format(self.__port))
        mgr_socket.send(b'PREPROCESSOR_READY')
        sockets = {}
        server_sessions = {}
        state = self.STATE_WAITING_FOR_TASK

        poller = zmq.Poller()
        poller.register(mgr_socket, zmq.POLLIN)

        while True:
            socks = dict(poller.poll())
            for sock, event in socks.items():
                assert event == zmq.POLLIN
                if sock is mgr_socket:
                    if state == self.STATE_WAITING_FOR_TASK:
                        tag, self.task = mgr_socket.recv_multipart()
                        assert tag == b'PREPROCESS_TASK'
                        self.task = pickle.loads(self.task)
                        timer = SimpleTimer()
                        self.header_info = list(self.header_info(self.task))
                        mgr_socket.send_multipart([b'PREPROCESSING_DONE', pickle.dumps(timer.get())])
                        state = self.STATE_WAITING_FOR_SERVER
                    else:
                        assert state == self.STATE_WAITING_FOR_SERVER
                        tag, server_id, node_index = mgr_socket.recv_multipart()
                        assert tag == b'SEND_TO_SERVER'
                        node_index = pickle.loads(node_index)
                        available_sockets = sockets.setdefault(node_index, [])
                        if available_sockets:
                            socket = available_sockets[0]
                            del available_sockets[0]
                        else:
                            socket = zmq_ctx.socket(zmq.DEALER)
                            socket.connect(self.__nodes[node_index]['address'])
                        socket.send_multipart([b'ATTACH_TO_SESSION', server_id])
                        poller.register(socket, zmq.POLLIN)
                        assert socket not in server_sessions
                        task = self.task
                        header_info = self.header_info
                        server_sessions[socket] = self.Session(self.task, self.header_info, node_index)
                        del self.task
                        del self.header_info
                        state = self.STATE_WAITING_FOR_TASK
                else:
                    assert sock in server_sessions
                    session = server_sessions[sock]
                    if session.state == self.Session.STATE_ATTACHING_TO_SESSION:
                        msg = sock.recv_multipart()
                        assert len(msg) == 1 and msg[0] == b'SESSION_ATTACHED'
                        sock.send_multipart([b'TASK_FILE_LIST', pickle.dumps(session.filelist)])
                        session.state = self.Session.STATE_SENDING_FILE_LIST
                    elif session.state == self.Session.STATE_SENDING_FILE_LIST:
                        resp = sock.recv_multipart()
                        assert len(resp) == 2 and resp[0] == b'MISSING_FILES'
                        missing_files = pickle.loads(resp[1])
                        new_tar = self.tar_with_new_headers(session.task, missing_files, session.header_info)
                        sock.send_multipart([b'TASK_FILES', new_tar.read()])
                        poller.unregister(sock)
                        sockets[session.node_index].append(sock)
                        del server_sessions[sock]
                        
                    else:
                        raise Exception("Invalid state.")

    @classmethod
    def header_beginning(cls, filename):
        return b''
        # 'sourceannotations.h' header is funny. If you add a #line directive to
        # it it will start tossing incomprehensible compiler erros. It would
        # seem that cl.exe has some hardcoded logic for this header. Person
        # responsible for this should be severely punished.
        if 'sourceannotations.h' in filename:
            return b''
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
                        file, abs, system, content, header, digest = next(header_info_iter)
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
            ignored_headers=[task['pch_header']] if task['pch_header'] else [])
        for file, abs, system, content in header_info:
            input = BytesIO(content)
            hash = md5()
            for chunk in iter(lambda : input.read(128 * hash.block_size), b''):
                hash.update(chunk)
            yield file, abs, system, content, cls.header_beginning(abs), hash.digest()
