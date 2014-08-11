from buildpal.common import SimpleTimer, send_file, send_compressed_file

from enum import Enum
from io import BytesIO

import asyncio
import logging
import os
import pickle
import zipfile
import zlib

from time import time

class SessionResult(Enum):
    success = 1
    failure = 2
    cancelled = 3
    too_late = 4
    timed_out = 5
    terminated = 6

class ServerSession:
    STATE_START = 0
    STATE_WAIT_FOR_MISSING_FILES = 1
    STATE_RECEIVE_OBJECT_FILE = 2
    STATE_WAIT_FOR_SERVER_RESPONSE = 3
    STATE_FINISH = 4

    class Sender:
        def __init__(self, send_msg, session_id):
            self._session_id = session_id
            self._send_msg = send_msg

        def send_msg(self, data):
            self._send_msg([self._session_id] + list(data))

    def __init__(self, id, task, send_msg, node, loop, executor, compressor,
                 completion_callback):
        self.state = self.STATE_START
        self.task = task
        self.node = node
        self.task.register_session(self)
        self.cancelled = False
        self.loop = loop
        self.executor = executor
        self.compressor = compressor
        self.result = None
        self.local_id = id
        self.send_msg = send_msg
        self.sender = None
        self.completion_callback = completion_callback

    def start(self):
        assert self.state == self.STATE_START
        self.send_msg([b'NEW_SESSION', self.local_id,
            b'SERVER_TASK', pickle.dumps(self.task.server_task)])
        self.state = self.STATE_WAIT_FOR_MISSING_FILES
        self.time_started = time()

    def cancel(self):
        if self.sender:
            self.sender.send_msg([b'CANCEL_SESSION'])
        self.cancelled = True

    def terminate(self):
        self.state = self.STATE_FINISH
        self.__complete(SessionResult.terminated)

    def __complete(self, result):
        self.state = self.STATE_FINISH
        self.time_completed = time()
        self.result = result
        self.completion_callback(self)

    @property
    def timer(self):
        return self.node.timer()

    def got_data_from_server(self, msg):
        if msg[0] == b'SESSION_CANCELLED':
            assert self.cancelled
            self.__complete(SessionResult.cancelled)
            return True
        elif msg[0] == b'TIMED_OUT':
            self.__complete(SessionResult.timed_out)
            return True

        # It is possible that cancellation arrived too late,
        # that the server already sent the final message and
        # unregistered its session. In that case we will never
        # get confirmation.

        # This state requires a response, so the session must be still alive
        # on the server.
        if self.state == self.STATE_WAIT_FOR_MISSING_FILES:
            assert len(msg) == 3 and msg[1] == b'MISSING_FILES'
            assert self.sender is None
            self.sender = self.Sender(self.send_msg, msg[0].tobytes())
            if self.cancelled:
                self.sender.send_msg([b'CANCEL_SESSION'])
            missing_files, need_compiler, need_pch = pickle.loads(msg[2].memory())
            task_files = [b'TASK_FILES']
            task_files.extend(self.task_files_bundle(missing_files))
            self.sender.send_msg(task_files)
            if need_compiler:
                zip_data = BytesIO()
                with zipfile.ZipFile(zip_data, mode='w') as zip_file:
                    for path, file in self.task.compiler_info.files:
                        if path:
                            zip_file.write(path.decode(), file.decode())
                send_file(self.sender.send_msg, BytesIO(zip_data.getbuffer()))
                del zip_data
            if need_pch:
                assert self.task.pch_file is not None
                def send_pch_file(fileobj):
                    send_file(self.sender.send_msg, fileobj)
                pch_file = os.path.join(os.getcwd(), self.task.pch_file[0])
                self.compressor.compress_file(pch_file, send_pch_file)
            self.state = self.STATE_WAIT_FOR_SERVER_RESPONSE

        elif self.state == self.STATE_WAIT_FOR_SERVER_RESPONSE:
            server_status = msg[0]
            if server_status == b'SERVER_FAILED':
                self.retcode = -1
                self.stdout = b''
                self.stderr = msg[1].tobytes()
                self.__complete(SessionResult.failure)
                return True
            else:
                assert server_status == b'SERVER_DONE'
                self.retcode, self.stdout, self.stderr, server_times = pickle.loads(msg[1].memory())
                logging.debug("Got {} retcode".format(self.retcode))
                for name, duration in server_times.items():
                    self.timer.add_time(name, duration)
                if self.task.register_completion(self):
                    assert not self.cancelled
                    if self.retcode == 0:
                        self.sender.send_msg([b'SEND_CONFIRMATION', b'\x01'])
                        self.obj_desc = BytesIO()
                        self.state = self.STATE_RECEIVE_OBJECT_FILE
                        self.result_futures = []
                        self.receive_result_time = SimpleTimer()
                    else:
                        self.__complete(SessionResult.success)
                        return True
                else:
                    if self.retcode == 0:
                        self.sender.send_msg([b'SEND_CONFIRMATION', b'\x00'])
                    self.__complete(SessionResult.too_late)
                    return True

        elif self.state == self.STATE_RECEIVE_OBJECT_FILE:
            assert not self.cancelled
            more, data = msg
            self.obj_desc.write(data.memory())
            if more == b'\x00':
                file_index = len(self.result_futures)
                future = self.loop.run_in_executor(self.executor,
                    self._decompress_to_disk, self.obj_desc,
                    self.task.result_files[file_index])
                self.result_futures.append(future)
            
                # Complete the session once all files are decompressed.
                if len(self.result_futures) == len(self.task.result_files):
                    self.timer.add_time('download result files',
                        self.receive_result_time.get())
                    asyncio.gather(*self.result_futures, loop=self.loop
                        ).add_done_callback(self.complete_session)
                    return True
                else:
                    # Prepare to receive another file.
                    self.obj_desc = BytesIO()
        else:
            assert not "Invalid state"
        return False

    @classmethod
    def _decompress_to_disk(cls, fileobj, output):
        fileobj.seek(0)
        decompressor = zlib.decompressobj()
        with open(output, "wb") as obj:
            for data in iter(lambda : fileobj.read(256 * 1024), b''):
                obj.write(decompressor.decompress(data))
            obj.write(decompressor.flush())
            logging.debug("Written {} bytes".format(obj.tell()))

    def complete_session(self, future):
        try:
            # We might have been terminated.
            if self.state == self.STATE_FINISH:
                assert self.result == SessionResult.terminated
                return
            future_count = len(future.result())
        except Exception as e:
            logging.exception(e)
            self.__complete(SessionResult.failure)
        else:
            assert future_count == len(self.task.result_files)
            self.__complete(SessionResult.success)


    def task_files_bundle(self, in_filelist):
        header_info = self.task.header_info
        source_file = self.task.source

        result = []
        for dir, system, data in header_info:
            dir_bytes = dir.encode()
            for file, relative, content_entry in data:
                if not relative and not (dir, file) in in_filelist:
                    continue
                result.extend((dir_bytes, file.encode(), content_entry.buffer()))

        with open(source_file, 'rb') as src:
            result.extend((b'', source_file.encode(), src.read()))
        return result

    def get_info(self):
        assert self.state == self.STATE_FINISH
        assert self.result is not None
        return {
            "hostname" : self.node.node_dict()['hostname'],
            "port" : self.node.node_dict()['port'],
            "started" : self.time_started,
            "completed" : self.time_completed,
            "result" : self.result,
        }
