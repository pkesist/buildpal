from Common import SimpleTimer, send_compressed_file, send_file

from subprocess import list2cmdline
from io import BytesIO

import os
import pickle
import zipfile
import zlib
import zmq

from time import time

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_PREPROCESSING_DONE = 1
    STATE_WAIT_FOR_SERVER_OK = 2
    STATE_WAIT_FOR_PCH_RESPONSE = 3
    STATE_WAIT_FOR_SERVER_RESPONSE = 4
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 5
    STATE_WAIT_FOR_COMPILER_FILE_LIST = 6
    STATE_RECEIVE_RESULT_FILE = 7
    STATE_POSTPROCESS = 8
    STATE_DONE = 9
    STATE_SERVER_FAILURE = 10

    def __init__(self, compiler, executable, task, client_conn, preprocess_socket,
        compiler_info):

        self.task = task
        self.client_conn = client_conn
        self.preprocess_socket = preprocess_socket
        self.compiler = compiler
        self.compiler_info = compiler_info
        self.executable = executable

        if self.executable in self.compiler_info:
            self.start_preprocessing()
        else:
            self.test_source = self.compiler.prepare_test_source(self.executable)
            self.client_conn.send([b'EXECUTE_GET_OUTPUT', list2cmdline(self.test_source.command()).encode()])
            self.state = self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT

    @property
    def timer(self):
        return self.node_info.timer()

    def start_preprocessing(self):
        assert self.executable in self.compiler_info
        self.task.compiler_info = self.compiler_info[self.executable]
        self.task.server_task_info['compiler_info'] = self.task.compiler_info
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros)
        self.preprocess_socket.send_multipart([b'PREPROCESS_TASK',
            pickle.dumps(self.task.preprocess_task_info)],
            copy=False)
        self.preprocessing_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_PREPROCESSING_DONE

    def got_data_from_client(self, msg):
        if self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT:
            self.test_source.destroy()
            del self.test_source
            retcode = int(msg[0])
            stdout = msg[1]
            stderr = msg[2]
            info = self.compiler.compiler_info(self.executable, stdout, stderr)
            self.compiler_info[self.executable] = info
            self.client_conn.send([b'LOCATE_FILES'] + info.compiler_files)
            self.state = self.STATE_WAIT_FOR_COMPILER_FILE_LIST
        elif self.state == self.STATE_WAIT_FOR_COMPILER_FILE_LIST:
            self.compiler_info[self.executable].files = msg
            self.start_preprocessing()

    def preprocessing_done(self, server_conn, node_info):
        assert self.state == self.STATE_WAIT_FOR_PREPROCESSING_DONE
        self.server_conn = server_conn
        self.node_info = node_info
        server_id = self.server_conn.getsockopt(zmq.IDENTITY)
        assert server_id
        self.preprocess_socket.send_multipart([b'SEND_TO_SERVER',
            server_id, pickle.dumps(self.node_info.index())], copy=False)
        self.server_conn.send_multipart([b'SERVER_TASK', pickle.dumps(self.task.server_task_info)])
        self.node_info.add_tasks_sent()
        self.server_time = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_SERVER_OK

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_SERVER_OK:
            compiler_state = msg[0]
            if compiler_state == b'NEED_COMPILER':
                ci = self.compiler_info[self.executable]
                assert hasattr(ci, 'files')
                assert hasattr(ci, 'compiler_files')
                zip_data = BytesIO()
                with zipfile.ZipFile(zip_data, mode='w') as zip_file:
                    for path, file in zip(ci.files, ci.compiler_files):
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
