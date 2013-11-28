from .scan_headers import collect_headers, cache_info

from Common import SimpleTimer, write_str_to_tar
from Common import create_socket, recv_multipart

import zmq
import tarfile
import os
import pickle
from zlib import adler32
from socket import getfqdn

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from multiprocessing import cpu_count


def header_beginning(filename):
    return b''
    # 'sourceannotations.h' header is funny. If you add a #line directive to
    # it it will start tossing incomprehensible compiler erros. It would
    # seem that cl.exe has some hardcoded logic for this header. Person
    # responsible for this should be severely punished.
    if 'sourceannotations.h' in filename:
        return b''
    pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
    return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

def header_info(task):
    header_info = collect_headers(task['source'], task['includes'],
        task['sysincludes'], task['macros'],
        ignored_headers=[task['pch_header']] if task['pch_header'] else [])
    return ((dir, file, relative, content, header_beginning(abs), \
        adler32(content)) for dir, file, relative, content in header_info)

class SourceScanner:
    def __init__(self, zmq_ctx, address, nodes, poller):
        self.zmq_ctx = zmq_ctx

        self.nodes = nodes
        self.address = address

        self.mgr_socket = create_socket(self.zmq_ctx, zmq.ROUTER)
        self.mgr_socket.bind(address)

        self.sessions_socket = create_socket(self.zmq_ctx, zmq.DEALER)
        self.sessions_socket.bind('inproc://pp_sessions')

        self.sockets = {}
        self.client_sessions = {}
        self.server_sessions = {}

        self.executor = ThreadPoolExecutor(2 * cpu_count())
        self.poller = poller

        self.poller.register(self.mgr_socket, zmq.POLLIN)
        self.poller.register(self.sessions_socket, zmq.POLLIN)

    def terminate(self):
        self.executor.shutdown()
        self.mgr_socket.unbind(self.address)
        self.sessions_socket.unbind('inproc://pp_sessions')
        self.poller.unregister(self.mgr_socket)
        self.poller.unregister(self.sessions_socket)

    class Session:
        STATE_WAITING_FOR_TASK = 1
        STATE_WAITING_FOR_SERVER = 2
        STATE_ATTACHING_TO_SESSION = 3
        STATE_SENDING_FILE_LIST = 4

        def __init__(self, zmq_ctx, conn_id, task, executor):
            self.state = self.STATE_WAITING_FOR_TASK
            self.conn_id = conn_id
            self.task = task
            def verify(future):
                future.result()
            executor.submit(self.calc_header_info, zmq_ctx).add_done_callback(verify)

        def calc_header_info(self, zmq_ctx):
            timer = SimpleTimer()
            self.header_info = list(header_info(self.task))
            self.filelist = self.create_filelist()
            hits, misses = cache_info()

            self.state = self.STATE_WAITING_FOR_SERVER
            s = create_socket(zmq_ctx, zmq.DEALER)
            s.connect('inproc://pp_sessions')
            s.send_multipart([self.conn_id,
                b'PREPROCESSING_DONE',pickle.dumps(timer.get()),
                pickle.dumps((hits, misses))])
            s.disconnect('inproc://pp_sessions')

        def create_filelist(self):
            return list((dir, file, relative, checksum) for dir, file, relative, \
                content, header, checksum in self.header_info)

    def handle(self, socket):
        if socket is self.mgr_socket:
            conn_id, *msg = recv_multipart(socket)
            session = self.client_sessions.get(conn_id)
            if not session:
                assert msg[0] == b'PREPROCESS_TASK'
                self.client_sessions[conn_id] = self.Session(self.zmq_ctx, conn_id, pickle.loads(msg[1]), self.executor)
            else:
                assert session.state == self.Session.STATE_WAITING_FOR_SERVER
                del self.client_sessions[conn_id]
                if msg[0] == b'SEND_TO_SERVER':
                    server_id, node_index = msg[1:]
                    node_index = pickle.loads(node_index)
                    session.node_index = node_index
                    available_sockets = self.sockets.setdefault(node_index, [])
                    if available_sockets:
                        socket = available_sockets[0]
                        del available_sockets[0]
                    else:
                        socket = create_socket(self.zmq_ctx, zmq.DEALER)
                        socket.connect(self.nodes[node_index]['address'])
                    socket.send_multipart([b'ATTACH_TO_SESSION', server_id])
                    self.poller.register(socket, zmq.POLLIN)
                    assert socket not in self.server_sessions
                    self.server_sessions[socket] = session
                    session.state = self.Session.STATE_ATTACHING_TO_SESSION
                else:
                    assert msg[0] == b'DROP'
            return True
        elif socket is self.sessions_socket:
            self.mgr_socket.send_multipart(recv_multipart(self.sessions_socket), copy=False)
            return True
        elif socket in self.server_sessions:
            session = self.server_sessions[socket]
            msg = recv_multipart(socket)
            if session.state == self.Session.STATE_ATTACHING_TO_SESSION:
                assert len(msg) == 1
                if msg[0] == b'SESSION_ATTACHED':
                    socket.send_multipart([b'TASK_FILE_LIST', getfqdn().encode(), pickle.dumps(session.filelist)])
                    session.wait_for_header_list_response = SimpleTimer()
                    session.state = self.Session.STATE_SENDING_FILE_LIST
                else:
                    assert msg[0] == b'UNKNOWN_SESSION'
                    # Huh. Weird.
                    self.poller.unregister(socket)
                    self.sockets[session.node_index].append(socket)
                    del self.server_sessions[socket]

            elif session.state == self.Session.STATE_SENDING_FILE_LIST:
                assert len(msg) == 2 and msg[0] == b'MISSING_FILES'
                missing_files = pickle.loads(msg[1])
                new_tar, src_loc = self.tar_with_new_headers(session.task, missing_files, session.header_info)
                socket.send_multipart([b'TASK_FILES', getfqdn().encode(), new_tar.read(), src_loc.encode(), pickle.dumps(session.wait_for_header_list_response.get())])
                self.poller.unregister(socket)
                self.sockets[session.node_index].append(socket)
                del self.server_sessions[socket]
            else:
                raise Exception("Invalid state.")
            return True
        return False

    @classmethod
    def tar_with_new_headers(cls, task, in_filelist, header_info):
        paths_to_include = []
        relative_includes = {}
        tar_buffer = BytesIO()
        rel_counter = 0
        max_depth = 0
        with tarfile.open(mode='w', fileobj=tar_buffer) as out_tar:
            header_info_iter = iter(header_info)
            for in_name in in_filelist:
                found = False
                while not found:
                    try:
                        dir, file, relative, content, header, checksum = next(header_info_iter)
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
                if relative:
                    while '..' in path_elements:
                        index = path_elements.index('..')
                        if index == 0:
                            depth += 1
                            if depth > max_depth:
                                max_depth += 1
                            del path_elements[index]
                        else:
                            del path_element[index - 1:index + 1]
                    if depth:
                        relative_includes.setdefault(depth - 1, []).append((dir, '/'.join(path_elements), content, header))
                    else:
                        write_str_to_tar(out_tar, '/'.join(path_elements), content, header)
                write_str_to_tar(out_tar, file, content, header)
            
            curr_dir = ''
            for depth in range(max_depth):
                curr_dir += 'dummy_rel/'
                for dir, file, content, header in relative_includes[depth]:
                    write_str_to_tar(out_tar, curr_dir + file, content, header)
            if paths_to_include:
                write_str_to_tar(out_tar, 'include_paths.txt', "\n".join(paths_to_include).encode())
            rel_file = curr_dir + os.path.basename(task['source'])
            cpp_file = task['source']
            with open(cpp_file, 'rb') as src:
                write_str_to_tar(out_tar, rel_file, src.read(), header_beginning(cpp_file))
        tar_buffer.seek(0)
        return tar_buffer, rel_file
