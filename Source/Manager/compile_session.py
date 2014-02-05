from .source_scanner import header_beginning

from Common import SimpleTimer, send_compressed_file, send_file

from io import BytesIO

import os
import pickle
import zipfile
import zlib
import zmq

from itertools import chain
from time import time

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_MISSING_FILES = 1
    STATE_RECEIVE_RESULT_FILE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_DONE = 4
    STATE_SERVER_FAILURE = 5
    STATE_CANCELLED = 6

    def __init__(self, task, server_conn, node):
        self.state = self.STATE_START
        self.task = task
        self.compiler = task.compiler()
        self.server_conn = server_conn
        self.node = node

    def start(self):
        assert self.state == self.STATE_START
        self.server_conn.send_multipart([b'SERVER_TASK', pickle.dumps(self.task.server_task_info)])
        self.node.add_tasks_sent()
        self.server_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_MISSING_FILES

    @property
    def timer(self):
        return self.node.timer()

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_MISSING_FILES:
            assert len(msg) == 2 and msg[0] == b'MISSING_FILES'
            missing_files, need_compiler, need_pch = pickle.loads(msg[1])
            new_files, src_loc = self.task_files_bundle(missing_files)
            self.server_conn.send_multipart([b'TASK_FILES',
                zlib.compress(pickle.dumps(new_files)), src_loc.encode()])
            if need_compiler:
                zip_data = BytesIO()
                with zipfile.ZipFile(zip_data, mode='w') as zip_file:
                    for path, file in self.task.compiler_files:
                        zip_file.write(path.decode(), file.decode())
                zip_data.seek(0)
                send_file(self.server_conn.send_multipart, zip_data)
                del zip_data
            if need_pch:
                assert self.task.pch_file is not None
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_multipart, pch_file, copy=False)
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_time = self.server_time.get()
            del self.server_time
            self.timer.add_time('server_time', server_time)
            self.node.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.node.add_tasks_failed()
                self.retcode = -1
                self.stdout = b''
                self.stderr = msg[1].tobytes()
                self.state = self.STATE_SERVER_FAILURE
                return True
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, server_times = pickle.loads(msg[1])
                for name, duration in server_times.items():
                    self.timer.add_time("server." + name, duration)
                if self.task.register_completion(self):
                    if self.retcode == 0:
                        self.server_conn.send_multipart([b'SEND_CONFIRMATION', b'\x01'])
                        self.output = open(self.task.output, "wb")
                        self.output_decompressor = zlib.decompressobj()
                        self.state = self.STATE_RECEIVE_RESULT_FILE
                        self.receive_result_time = SimpleTimer()
                    else:
                        self.node.add_tasks_completed()
                        self.state = self.STATE_DONE
                        return True
                else:
                    self.state = self.STATE_CANCELLED
                    if self.retcode == 0:
                        self.server_conn.send_multipart([b'SEND_CONFIRMATION', b'\x00'])
                    return True

        elif self.state == self.STATE_RECEIVE_RESULT_FILE:
            more, data = msg
            self.output.write(self.output_decompressor.decompress(data))
            if more == b'\x00':
                self.output.write(self.output_decompressor.flush())
                del self.output_decompressor
                self.timer.add_time('receive_result', self.receive_result_time.get())
                del self.receive_result_time
                self.output.close()
                del self.output
                self.node.add_tasks_completed()
                self.state = self.STATE_DONE
                return True
        return False

    def task_files_bundle(self, in_filelist):
        header_info = self.task.header_info
        source_file = self.task.source

        relative_includes = {}
        rel_counter = 0
        max_depth = 0
        files = {}
        # Iterate over
        #
        #    (dir1, [[a11, a12], [b11, b12]]),
        #    (dir2, [[a21, a22], [b21, b22]]),
        #
        #
        # Like it was
        #
        #  (dir1, a11, a12),
        #  (dir1, b11, b12),
        #  (dir2, a21, a22),
        #  (dir2, b21, b22),
        #
        #
        #
        header_info_iter = chain(*list([([dir] + info) for info in data] for dir, data in header_info))
        for entry in in_filelist:
            found = False
            while not found:
                try:
                    dir, file, relative, content, checksum, header = \
                        next(header_info_iter)
                    if entry == (dir, file):
                        assert not relative
                        found = True
                        break
                    elif relative:
                        break
                except StopIteration:
                    raise Exception("Could not find information for {}.".format(
                        in_name))
            assert found or relative
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
                    relative_includes.setdefault(depth - 1, []).append((dir,
                        '/'.join(path_elements), content, header))
                else:
                    files['/'.join(path_elements)] = header + content
            else:
                files[(dir, file)] = header + content
            
        curr_dir = ''
        for depth in range(max_depth):
            assert relative
            curr_dir += 'dummy_rel/'
            for dir, file, content, header in relative_includes[depth]:
                files[('', curr_dir + file)] = header + content
        rel_file = curr_dir + os.path.basename(source_file)
        with open(source_file, 'rb') as src:
            files[('', rel_file)] = header_beginning(source_file) + src.read()
        return files, rel_file
