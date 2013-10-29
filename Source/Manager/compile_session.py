from Common import SimpleTimer, send_compressed_file

from subprocess import list2cmdline

import os
import pickle
import zlib
import zmq

class CompileSession:
    STATE_START = 0
    STATE_WAIT_FOR_PREPROCESSING_DONE = 1
    STATE_WAIT_FOR_SERVER_OK = 2
    STATE_WAIT_FOR_PCH_RESPONSE = 3
    STATE_WAIT_FOR_SERVER_RESPONSE = 4
    STATE_WAIT_FOR_COMPILER_INFO_OUTPUT = 5
    STATE_RECEIVE_RESULT_FILE = 6
    STATE_POSTPROCESS = 7
    STATE_WAIT_FOR_SESSION_DONE = 8

    def __init__(self, compiler, executable, task, client_conn, preprocess_socket,
        preprocessor_id, compiler_info):

        self.task = task
        self.client_conn = client_conn
        self.preprocess_socket = preprocess_socket
        self.preprocessor_id = preprocessor_id
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
        self.task.preprocess_task_info['macros'].extend(self.task.compiler_info.macros())
        self.preprocess_socket.send_multipart([self.preprocessor_id, b'PREPROCESS_TASK',
            pickle.dumps(self.task.preprocess_task_info)],
            copy=False)
        self.state = self.STATE_WAIT_FOR_PREPROCESSING_DONE

    def got_data_from_client(self, msg):
        assert self.state == self.STATE_WAIT_FOR_COMPILER_INFO_OUTPUT
        self.test_source.destroy()
        del self.test_source
        retcode = int(msg[0])
        stdout = msg[1]
        stderr = msg[2]
        info = self.compiler.compiler_info(self.executable, stdout, stderr)
        self.compiler_info[self.executable] = info
        self.start_preprocessing()

    def preprocessing_done(self, server_conn, node_info):
        assert self.state == self.STATE_WAIT_FOR_PREPROCESSING_DONE
        self.server_conn = server_conn
        self.node_info = node_info
        server_id = self.server_conn.getsockopt(zmq.IDENTITY)
        assert server_id
        self.preprocess_socket.send_multipart([self.preprocessor_id, b'SEND_TO_SERVER',
            server_id, pickle.dumps(self.node_info.index())], copy=False)
        self.server_conn.send_pyobj(self.task.server_task_info)
        self.node_info.add_tasks_sent()
        self.average_timer = SimpleTimer()
        self.state = self.STATE_WAIT_FOR_SERVER_OK
        del self.preprocessor_id

    def got_data_from_server(self, msg):
        if self.state == self.STATE_WAIT_FOR_SERVER_OK:
            task_ok = msg[0]
            assert msg[0] == b'OK'
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
            server_time = self.average_timer.get()
            del self.average_timer
            self.timer.add_time('server_time', server_time)
            self.node_info.add_total_time(server_time)
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.client_conn.send([b'EXIT', b'-1'])
                self.state = self.STATE_WAIT_FOR_SESSION_DONE
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
                    self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                    self.node_info.add_tasks_completed()
                    self.state = self.STATE_WAIT_FOR_SESSION_DONE

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
                self.client_conn.send([b'COMPLETED', str(self.retcode).encode(), self.stdout, self.stderr])
                self.node_info.add_tasks_completed()
                self.state = self.STATE_WAIT_FOR_SESSION_DONE
        elif self.state == self.STATE_WAIT_FOR_SESSION_DONE:
            assert msg[0] == b'SESSION_DESTROYED'
            return True
        return False
