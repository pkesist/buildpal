from scan_headers import collect_headers

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib

from utils import TempFile, send_file, receive_file, receive_compressed_file
from multiprocessing.connection import Client

class CompileTask:
    def __init__(self, cwd, call, source, source_type, input, search_path, defines, output, compiler_info, distributer):
        self.__call = call
        self.__cwd = cwd
        self.__source = source
        self.__input = input
        self.__search_path = search_path
        self.__defines = defines
        self.__source_type = source_type
        self.__output = output
        self.__compiler_info = compiler_info
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()
        self.__tempfile = None

        self.__algorithm = 'SCAN_HEADERS'
        #self.__algorithm = 'PREPROCESS_LOCALLY'

    def manager_prepare(self, manager_ctx):
        if self.__algorithm == 'SCAN_HEADERS':
            cache = {}
            missing = set()
            defines = self.__defines + [
                '_MSC_VER=1500',
                '_MSC_FULL_VER=150030729',
                '_CPPLIB_VER=505',
                '__cplusplus',
                '_WIN32',
                '_MSC_EXTENSIONS=1',
                '_MT=1',
                '_CPPUNWIND',
                '_HAS_TR1=1',
                '_M_IX86=600',
                '_NATIVE_WCHAR_T_DEFINED=1',
                '_HAS_ITERATOR_DEBUGGING=1',
                '_DEBUG',
                '_CPPRTTI']

            tempFile = collect_headers(self.__source, self.__cwd, self.__search_path, defines, cache)
            if tempFile:
                self.__tempfile = tempFile
            else:
                self.__algorithm = 'PREPROCESS_LOCALLY'

        if self.__algorithm == 'PREPROCESS_LOCALLY':
            # Signal the client to do preprocessing.
            manager_ctx.client_conn.send('PREPROCESS')
            # Wait for 'done'.
            done = manager_ctx.client_conn.recv()
            assert done == 'DONE'
        return True

    def manager_send(self, manager_ctx):
        if self.__algorithm == 'SCAN_HEADERS':
            manager_ctx.server_conn.send('SCAN_HEADERS')
            with open(self.__tempfile.filename(), 'rb') as file:
                send_file(manager_ctx.server_conn, file)
            manager_ctx.server_conn.send('SOURCE_FILE')
            with open(os.path.join(self.__cwd, self.__source), 'rb') as cpp:
                send_file(manager_ctx.server_conn, cpp)

        if self.__algorithm == 'PREPROCESS_LOCALLY':
            manager_ctx.server_conn.send('PREPROCESS_LOCALLY')
            with open(self.__input, "rb") as file:
                send_file(manager_ctx.server_conn, file)

    def manager_receive(self, manager_ctx):
        retcode, stdout, stderr = manager_ctx.server_conn.recv()
        if retcode == 0:
            more = True
            with open(self.__output, "wb") as file:
                while more:
                    more, data = manager_ctx.server_conn.recv()
                    file.write(data)
        manager_ctx.client_conn.send('COMPLETED')
        manager_ctx.client_conn.send((retcode, stdout, stderr))
        return True

    def server_process(self, server, conn):
        accept = server.accept()
        compiler = server.setup_compiler(self.__compiler_info)
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        task = conn.recv()
        if task == 'SCAN_HEADERS':
            with receive_file(conn) as zip_file:
                include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
                with zipfile.ZipFile(zip_file.filename(), 'r') as zip:
                    zip.extractall(path=include_path)

                src_file = conn.recv()
                assert src_file == 'SOURCE_FILE'
                with receive_file(conn, suffix=self.__source_type) as source_file:
                    with TempFile(suffix='.obj') as object_file:
                        noLink = self.__compile_switch
                        output = self.__output_switch.format(object_file.filename())

                        defines = ['-D{}'.format(define) for define in self.__defines]
                        retcode, stdout, stderr = compiler(self.__call + defines + [noLink, output, '-I{}'.format(include_path), source_file.filename()])
                        conn.send('SERVER_DONE')
                        needsResult = conn.recv()
                        if not needsResult:
                            return
                        conn.send((retcode, stdout, stderr))
                        if retcode == 0:
                            with object_file.open('rb') as file:
                                send_file(conn, file)
                        shutil.rmtree(include_path, ignore_errors=True)

        if task == 'PREPROCESS_LOCALLY':
            with receive_compressed_file(conn) as preprocessed_file:
                with TempFile(suffix='.obj') as object_file:
                    noLink = self.__compile_switch
                    output = self.__output_switch.format(object_file.filename())
                    retcode, stdout, stderr = compiler(self.__call + [noLink, output, preprocessed_file.filename()])
                    conn.send('SERVER_DONE')
                    needsResult = conn.recv()
                    if not needsResult:
                        return
                    conn.send((retcode, stdout, stderr))
                    if retcode == 0:
                        with object_file.open('rb') as file:
                            send_file(conn, file)
