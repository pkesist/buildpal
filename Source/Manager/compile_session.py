from Common import SimpleTimer, send_file, send_compressed_file

from io import BytesIO

import os
import pickle
import zipfile
import zlib
import zmq

from time import time

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_MISSING_FILES = 1
    STATE_RECEIVE_RESULT_FILE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_DONE = 4
    STATE_SERVER_FAILURE = 5
    STATE_CANCELLED = 6
    STATE_TOO_LATE = 7
    STATE_TIMED_OUT = 8

    def __init__(self, task, server_conn, node, compressor):
        self.state = self.STATE_START
        self.task = task
        self.node = node
        self.task.register_session(self)
        self.compiler = task.compiler()
        self.server_conn = server_conn
        self.cancelled = False
        self.compressor = compressor

    def start(self):
        assert self.state == self.STATE_START
        self.server_conn.send_multipart([b'SERVER_TASK', pickle.dumps(self.task.server_task_info)])
        self.server_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_MISSING_FILES

    def cancel(self):
        self.server_conn.send_multipart([b'CANCEL_SESSION'])
        self.cancelled = True

    @property
    def timer(self):
        return self.node.timer()

    def got_data_from_server(self, msg):
        if msg[0] == b'SESSION_CANCELLED':
            assert self.cancelled
            if self.state != self.STATE_TOO_LATE:
                self.state = self.STATE_CANCELLED
            return True
        elif msg[0] == b'TIMED_OUT':
            self.state = self.STATE_TIMED_OUT
            return True
        # It is possible that cancellation arrived too late,
        # that the server already sent the final message and
        # unregistered its session. In that case we will never
        # get confirmation.

        # This state requires a response, so the session must be still alive
        # on the server.
        if not self.cancelled and self.state == self.STATE_WAIT_FOR_MISSING_FILES:
            assert len(msg) == 2 and msg[0] == b'MISSING_FILES'
            missing_files, need_compiler, need_pch = pickle.loads(msg[1])
            new_files, src_loc = self.task_files_bundle(missing_files)
            self.server_conn.send_multipart([b'TASK_FILES',
                pickle.dumps(new_files), src_loc.encode()])
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
                def send_pch_file(fileobj):
                    send_file(self.server_conn.send_multipart, fileobj, copy=False)
                pch_file = os.path.join(os.getcwd(), self.task.pch_file[0])
                self.compressor.compress(pch_file, send_pch_file)
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_time = self.server_time.get()
            del self.server_time
            self.timer.add_time('cumulative task time', server_time)
            self.node.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.retcode = -1
                self.stdout = b''
                self.stderr = msg[1].tobytes()
                self.state = self.STATE_CANCELLED if self.cancelled else self.STATE_SERVER_FAILURE
                return True
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, server_times = pickle.loads(msg[1])
                for name, duration in server_times.items():
                    self.timer.add_time(name, duration)
                if self.task.register_completion(self):
                    # We could not have been cancelled if we completed the task.
                    assert not self.cancelled
                    if self.retcode == 0:
                        self.server_conn.send_multipart([b'SEND_CONFIRMATION', b'\x01'])
                        self.obj_desc = open(self.task.output, "wb")
                        self.obj_decompressor = zlib.decompressobj()
                        self.state = self.STATE_RECEIVE_RESULT_FILE
                        self.receive_result_time = SimpleTimer()
                    else:
                        self.state = self.STATE_DONE
                        return True
                else:
                    self.state = self.STATE_TOO_LATE
                    if not self.cancelled and self.retcode == 0:
                        self.server_conn.send_multipart([b'SEND_CONFIRMATION', b'\x00'])
                    return not self.cancelled or self.retcode != 0

        elif self.state == self.STATE_RECEIVE_RESULT_FILE:
            assert not self.cancelled
            more, data = msg
            self.obj_desc.write(self.obj_decompressor.decompress(data))
            if more == b'\x00':
                self.obj_desc.write(self.obj_decompressor.flush())
                self.timer.add_time('download object file', self.receive_result_time.get())
                del self.receive_result_time
                self.obj_desc.close()
                self.state = self.STATE_DONE
                return True
        return False

    @classmethod
    def header_beginning(cls, filename):
        # 'sourceannotations.h' header is funny. If you add a #line directive to
        # it it will start tossing incomprehensible compiler erros. It would
        # seem that cl.exe has some hardcoded logic for this header. Person
        # responsible for this should be severely punished.
        if 'sourceannotations.h' in filename:
            return b''
        pretty_filename = os.path.normpath(filename).replace('\\', '\\\\')
        return '#line 1 "{}"\r\n'.format(pretty_filename).encode()

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
        header_info_iter = ((dir, stuff) for dir, data in header_info for stuff in data)
        for entry in in_filelist:
            found = False
            while not found:
                try:
                    dir, (file, relative, content, checksum) = \
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
            header = self.header_beginning(os.path.join(dir, file))
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
            files[('', rel_file)] = self.header_beginning(source_file) + src.read()
        return files, rel_file
