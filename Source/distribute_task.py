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
    def __init__(self, cwd, call, source, source_type, input, search_path, macros, builtin_macros, output, compiler_info, distributer):
        self.__call = call
        self.__cwd = cwd
        self.__source = source
        self.__input = input
        self.__search_path = search_path
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
        macros = self.__macros + self.__builtin_macros + ['__cplusplus=200406']
        from scan_headers import collect_headers
        return collect_headers(os.path.join(self.__cwd, self.__source), self.__search_path, macros)

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

                        defines = ['-D{}'.format(define) for define in self.__macros]
                        retcode, stdout, stderr = compiler(self.__call + defines + [noLink, output, '-I{}'.format(include_path), source_file.filename()])
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
                        shutil.rmtree(include_path, ignore_errors=True)

        if task == 'PREPROCESS_LOCALLY':
            tmp = utils.TempFile()
            with tmp.open('wb') as temp:
                receive_compressed_file(conn, temp)

            with tmp as preprocessed_file:
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
