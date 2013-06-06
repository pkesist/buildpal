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
    def __init__(self, cwd, call, source, source_type, input, includes, sysincludes, macros, builtin_macros, output, compiler_info, distributer):
        self.__call = call
        self.__cwd = cwd
        self.__source = source
        self.__input = input
        self.__includes = includes
        self.__sysincludes = sysincludes
        self.__macros = macros
        self.__builtin_macros = builtin_macros
        self.__source_type = source_type
        self.__output = output
        self.__compiler_info = compiler_info
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()
        self.tempfile = None

        self.algorithm = 'SCAN_HEADERS'
        #self.algorithm = 'PREPROCESS_LOCALLY'

    def manager_prepare(self):
        macros = self.__macros + self.__builtin_macros
        from scan_headers import collect_headers

        # TODO: This does not belong here. Move this to msvc.py.
        # We would like to avoid scanning system headers here if possible.
        # If we do so, we lose any preprocessor side-effects. We try to
        # hardcode this knowledge here.
        if '_DEBUG' in macros:
            if not any(('_SECURE_SCL' in x for x in macros)):
                macros.append('_SECURE_SCL=1')
            if not any(('_HAS_ITERATOR_DEBUGGING' in x for x in macros)):
                macros.append('_HAS_ITERATOR_DEBUGGING=1')
        return collect_headers(os.path.join(self.__cwd, self.__source), self.__includes, [], macros, self.__compiler_info)

    def manager_send(self, client_conn, server_conn):
        if self.algorithm == 'SCAN_HEADERS':
            server_conn.send('SCAN_HEADERS')
            with open(self.tempfile, 'rb') as file:
                send_file(server_conn, file)
            server_conn.send('SOURCE_FILE')
            with open(os.path.join(self.__cwd, self.__source), 'rb') as cpp:
                send_file(server_conn, cpp)

        if self.algorithm == 'PREPROCESS_LOCALLY':
            server_conn.send('PREPROCESS_LOCALLY')
            with open(self.__input, "rb") as file:
                send_file(server_conn, file)

    def manager_receive(self, client_conn, server_conn):
        retcode, stdout, stderr = server_conn.recv()
        if retcode == 0:
            length = 0
            more = True
            with open(self.__output, "wb") as file:
                receive_compressed_file(server_conn, file)
        client_conn.send('COMPLETED')
        client_conn.send((retcode, stdout, stderr))
        return True

    def server_process(self, server, conn):
        accept = server.accept()
        compiler = server.setup_compiler(self.__compiler_info)
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        algorithm = conn.recv()
        if algorithm == 'SCAN_HEADERS':
            with receive_file(conn) as zip_file:
                include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
                with zipfile.ZipFile(zip_file.filename(), 'r') as zip:
                    zip.extractall(path=include_path)
                try:
                    src_file = conn.recv()
                    assert src_file == 'SOURCE_FILE'
                    with receive_file(conn, suffix=self.__source_type) as source_file:
                        with TempFile(suffix='.obj') as object_file:
                            noLink = self.__compile_switch
                            output = self.__output_switch.format(object_file.filename())

                            defines = ['-D{}'.format(define) for define in self.__macros]
                            try:
                                retcode, stdout, stderr = compiler(self.__call + defines + [noLink, output, '-I{}'.format(include_path), source_file.filename()])
                            except Exception:
                                conn.send('SERVER_FAILED')
                                return
                            conn.send('SERVER_DONE')
                            needsResult = conn.recv()
                            if not needsResult:
                                return
                            conn.send((retcode, stdout, stderr))
                            if retcode == 0:
                                compressor = zlib.compressobj(1)
                                with object_file.open('rb') as obj:
                                    for data in iter(lambda : obj.read(1024 * 1024), b''):
                                        compressed = compressor.compress(data)
                                        conn.send((True, compressed))
                                    compressed = compressor.flush(zlib.Z_FINISH)
                                    conn.send((False, compressed))
                finally:
                    shutil.rmtree(include_path, ignore_errors=True)

        if algorithm == 'PREPROCESS_LOCALLY':
            tmp = TempFile()
            with tmp.open('wb') as temp:
                receive_compressed_file(conn, temp)

            with tmp as preprocessed_file:
                with TempFile(suffix='.obj') as object_file:
                    noLink = self.__compile_switch
                    output = self.__output_switch.format(object_file.filename())
                    try:
                        retcode, stdout, stderr = compiler(self.__call + [noLink, output, preprocessed_file.filename()])
                    except Exception:
                        conn.send('SERVER_FAILED')
                        return
                    conn.send('SERVER_DONE')
                    needsResult = conn.recv()
                    if not needsResult:
                        return
                    conn.send((retcode, stdout, stderr))
                    if retcode == 0:
                        compressor = zlib.compressobj(1)
                        with object_file.open('rb') as obj:
                            for data in iter(lambda : obj.read(1024 * 1024), b''):
                                compressed = compressor.compress(data)
                                conn.send((True, compressed))
                            compressed = compressor.flush(zlib.Z_FINISH)
                            conn.send((False, compressed))
