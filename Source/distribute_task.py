import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
import io

from utils import TempFile, send_file, receive_compressed_file, send_compressed_file, relay_file
from multiprocessing.connection import Client
from time import sleep

class CompileTask:
    def __init__(self, cwd, call, source, source_type, preprocessor_info, output, compiler_info, pch_file, pch_header, distributer):
        self.call = call
        self.source_type = source_type
        self.compiler_info = compiler_info
        self.output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.compile_switch = distributer.compile_no_link_option().make_value().make_str()
        self.cwd = cwd
        self.preprocessor_info = preprocessor_info
        self.pch_file = pch_file
        self.pch_header = pch_header
        self.output = output
        self.source = source
        self.tempfile = None

        self.algorithm = 'SCAN_HEADERS'
        #self.algorithm = 'PREPROCESS_LOCALLY_WITH_BUILTIN_PREPROCESSOR'
        #self.algorithm = 'REWRITE_INCLUDES'
        #self.algorithm = 'PREPROCESS_LOCALLY'

    def manager_send(self, client_conn, server_conn, prepare_pool, timer):
        if self.algorithm == 'SCAN_HEADERS':
            server_conn.send_pyobj('SCAN_HEADERS')
            server_conn.send_pyobj('ZIP_FILE')
            with timer.timeit('prepare_result'):
                tempfile = prepare_pool.get_result(self.tempfile)
            assert tempfile
            with timer.timeit('send.zip'), open(tempfile, 'rb') as file:
                send_file(server_conn.send_pyobj, file)
            server_conn.send_pyobj('SOURCE_FILE')
            with timer.timeit('send.source'), open(os.path.join(self.cwd, self.source), 'rb') as cpp:
                send_compressed_file(server_conn.send_pyobj, cpp)
            if self.pch_file:
                server_conn.send_pyobj('NEED_PCH_FILE')
                response = server_conn.recv_pyobj()
                if response == "YES":
                    with timer.timeit('send.pch'), open(os.path.join(os.getcwd(), self.pch_file[0]), 'rb') as pch_file:
                        send_compressed_file(server_conn.send_pyobj, pch_file)
                else:
                    assert response == "NO"

        if self.algorithm == 'PREPROCESS_LOCALLY':
            server_conn.send('PREPROCESS_LOCALLY')
            # Signal the client to do preprocessing.
            client_conn.send('PREPROCESS')
            server_conn.send('PREPROCESSED_FILE')
            relay_file(client_conn.recv, server_conn.send_pyobj)

        if self.algorithm == 'REWRITE_INCLUDES':
            server_conn.send_pyobj('PREPROCESS_LOCALLY')
            with timer.timeit('prepare_result'):
                tempfile = prepare_pool.get_result(self.tempfile)
            server_conn.send_pyobj('PREPROCESSED_FILE')
            send_compressed_file(server_conn.send_pyobj, io.BytesIO(tempfile))

        if self.algorithm == 'PREPROCESS_LOCALLY_WITH_BUILTIN_PREPROCESSOR':
            server_conn.send_pyobj('PREPROCESS_LOCALLY')
            from scan_headers import preprocess_file
            macros = self.preprocessor_info.macros + self.preprocessor_info.builtin_macros
            preprocessed_data = preprocess_file(
                os.path.join(self.cwd, self.source),
                self.preprocessor_info.includes,
                self.preprocessor_info.sysincludes,
                macros, self.compiler_info)
            send_compressed_file(server_conn.send_pyobj, io.BytesIO(preprocessed_data))

    def manager_receive(self, client_conn, server_conn, timer):
        with timer.timeit("receive.server"):
            retcode, stdout, stderr = server_conn.recv_pyobj()
        if retcode == 0:
            length = 0
            more = True
            with timer.timeit("receive.object"), open(self.output, "wb") as file:
                receive_compressed_file(server_conn.recv_pyobj, file)
        with timer.timeit("receive.client"):
            client_conn.send('COMPLETED')
            client_conn.send((retcode, stdout, stderr))
