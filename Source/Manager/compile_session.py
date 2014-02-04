from .source_scanner import header_beginning

from Common import SimpleTimer, send_compressed_file, send_file

from subprocess import list2cmdline
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
    STATE_WAIT_FOR_PREPROCESSING_DONE = 1
    STATE_WAIT_FOR_HEADER_FILE_LIST = 2
    STATE_WAIT_FOR_SERVER_OK = 3
    STATE_WAIT_FOR_PCH_RESPONSE = 4
    STATE_WAIT_FOR_SERVER_RESPONSE = 5
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 6
    STATE_WAIT_FOR_COMPILER_FILE_LIST = 7
    STATE_RECEIVE_RESULT_FILE = 8
    STATE_POSTPROCESS = 9
    STATE_DONE = 10
    STATE_SERVER_FAILURE = 11

    def __init__(self, task, preprocess_worker, compiler_info):
        self.task = task
        self.client_conn = task.client_conn
        self.compiler = task.compiler()
        self.executable = task.executable()
        self.compiler_info = compiler_info
        self.preprocess_worker = preprocess_worker

    def begin(self):
        if self.executable in self.compiler_info:
            self.start_preprocessing()
        else:
            self.test_source = self.compiler.prepare_test_source()
            self.client_conn.send([b'EXECUTE_GET_OUTPUT', list2cmdline(self.test_source.command()).encode()])
            self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    @property
    def timer(self):
        return self.node_info.timer()

    def rewind(self):
        assert self.state == self.STATE_SERVER_FAILURE
        self.state = self.STATE_WAIT_FOR_PREPROCESSING_DONE

    def start_preprocessing(self):
        assert self.executable in self.compiler_info
        self.task.compiler_info = self.compiler_info[self.executable]
        self.task.server_task_info['compiler_info'] = self.task.compiler_info
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info['macros'])
        self.preprocess_worker(self)
        self.preprocessing_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_PREPROCESSING_DONE

    def preprocessing_done(self, server_conn, node_info):
        assert self.state == self.STATE_WAIT_FOR_PREPROCESSING_DONE
        self.server_conn = server_conn
        self.node_info = node_info
        self.server_conn.send_multipart([b'SERVER_TASK', pickle.dumps(self.task.server_task_info)])
        self.node_info.add_tasks_sent()
        self.server_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_HEADER_FILE_LIST

    def got_data_from_client(self, msg):
        if self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT:
            self.test_source.destroy()
            del self.test_source
            retcode = int(msg[0])
            stdout = msg[1]
            stderr = msg[2]
            info = self.compiler.compiler_info(self.executable, stdout, stderr)
            self.compiler_info[self.executable] = info
            self.client_conn.send([b'LOCATE_FILES'] + info['compiler_files'])
            self.state = self.STATE_WAIT_FOR_COMPILER_FILE_LIST
        elif self.state == self.STATE_WAIT_FOR_COMPILER_FILE_LIST:
            self.compiler_info[self.executable]['files'] = msg
            self.start_preprocessing()

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_HEADER_FILE_LIST:
            assert len(msg) == 2 and msg[0] == b'MISSING_FILES'
            missing_files = pickle.loads(msg[1])
            new_files, src_loc = self.task_files_bundle(missing_files)
            self.server_conn.send_multipart([b'TASK_FILES',
                zlib.compress(pickle.dumps(new_files)), src_loc.encode()])
            self.state = self.STATE_WAIT_FOR_SERVER_OK

        elif self.state == self.STATE_WAIT_FOR_SERVER_OK:
            compiler_state = msg[0]
            if compiler_state == b'NEED_COMPILER':
                ci = self.compiler_info[self.executable]
                assert 'files' in ci
                assert 'compiler_files' in ci
                zip_data = BytesIO()
                with zipfile.ZipFile(zip_data, mode='w') as zip_file:
                    for path, file in zip(ci['files'], ci['compiler_files']):
                        zip_file.write(path.decode(), file.decode())
                zip_data.seek(0)
                send_file(self.server_conn.send_multipart, zip_data)
                del zip_data
            else:
                assert compiler_state == b'READY'

            if self.task.pch_file:
                self.server_conn.send(b'NEED_PCH_FILE')
                self.state = self.STATE_WAIT_FOR_PCH_RESPONSE
            else:
                self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_PCH_RESPONSE:
            response = msg[0]
            if response == b'YES':
                with self.timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.task.pch_file[0]), 'rb') as pch_file:
                    send_compressed_file(self.server_conn.send_multipart, pch_file, copy=False)
            else:
                assert response == b'NO'
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_time = self.server_time.get()
            del self.server_time
            self.timer.add_time('server_time', server_time)
            self.node_info.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.node_info.add_tasks_failed()
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
                if self.retcode == 0:
                    self.output = open(self.task.output, "wb")
                    self.output_decompressor = zlib.decompressobj()
                    self.state = self.STATE_RECEIVE_RESULT_FILE
                    self.receive_result_time = SimpleTimer()
                else:
                    self.node_info.add_tasks_completed()
                    self.state = self.STATE_DONE
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
                self.node_info.add_tasks_completed()
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
        #    ....
        #
        # Like it was
        #
        #  (dir1, a11, a12),
        #  (dir1, b11, b12),
        #  (dir2, a21, a22),
        #  (dir2, b21, b22),
        #  ...
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
