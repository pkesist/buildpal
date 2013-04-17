from scan_headers import collect_headers

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib

from utils import TempFile
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

    def manager_prepare(self, server_conn, client_conn):
        # Try to pack all required headers.
        cache = {}
        missing = set()
        zip = TempFile(suffix='.zip')
        defines = self.__defines + ['_MSC_VER=1500', '_MSC_FULL_VER=150030729', '_CPPLIB_VER=505', '__cplusplus', '_WIN32', '_MSC_EXTENSIONS=1', '_MT=1', '_CPPUNWIND']

        if collect_headers(self.__source, self.__cwd, self.__search_path, defines, cache, zip.filename()):
            self.__tempfile = zip
        else:
            print("Failed to determine required headers, preprocessing...")
            # Signal the client to do preprocessing.
            client_conn.send("PREPROCESS")
            # Wait for 'done'.
            done = client_conn.recv()
            assert done == "DONE"
        return True

    def manager_send(self, server_conn, client_conn):
        if self.__tempfile:
            server_conn.send("WITH_HEADERS")
            with open(self.__tempfile.filename(), 'rb') as file:
                for data in iter(lambda : file.read(10 * 1024), b''):
                    server_conn.send((True, data))
                server_conn.send((False, b''))
            with open(os.path.join(self.__cwd, self.__source), 'rb') as cpp:
                for data in iter(cpp.readline, b''):
                    server_conn.send((True, data))
                server_conn.send((False, b''))
        else:
            server_conn.send("PREPROCESSED")
            with open(self.__input, "rb") as file:
                for data in iter(lambda : file.read(10 * 1024), b''):
                    server_conn.send((True, data))
                server_conn.send((False, b''))

    def manager_receive(self, server_conn, client_conn):
        retcode, stdout, stderr = server_conn.recv()
        if retcode == 0:
            more = True
            with open(self.__output, "wb") as file:
                while more:
                    more, data = server_conn.recv()
                    file.write(data)
        client_conn.send("COMPLETED")
        client_conn.send((retcode, stdout, stderr))
        print("Notified client")
        return True

    def server_process(self, server, conn):
        accept = server.accept()
        compiler = server.setup_compiler(self.__compiler_info)
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        def receive_file(*args, **kwargs):
            tempfile = TempFile(*args, **kwargs)
            with tempfile.open('wb') as file:
                more = True
                while more:
                    more, data = conn.recv()
                    file.write(data)
            return tempfile

        def receive_compressed_file():
            more = True
            tempfile = TempFile()
            decompressor = zlib.decompressobj()
            with tempfile.open('wb') as file:
                while more:
                    more, data = conn.recv()
                    file.write(decompressor.decompress(data))
                file.write(decompressor.flush())
            return tempfile

        def send_file(fileobj):
            with fileobj.open("rb") as file:
                for data in iter(lambda : file.read(10 * 1024), b''):
                    conn.send((True, data))
                conn.send((False, b''))

        
        task = conn.recv()
        if task == "WITH_HEADERS":       
            with receive_file() as zip_file:
                include_path =  tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
                with zipfile.ZipFile(zip_file.filename(), 'r') as zip:
                    zip.extractall(path=include_path)
            
                with receive_file(suffix=self.__source_type) as source_file:
                    with TempFile(suffix='.obj') as object_file:
                        noLink = self.__compile_switch
                        output = self.__output_switch.format(object_file.filename())

                        defines = ['-D{}'.format(define) for define in self.__defines]
                        retcode, stdout, stderr = compiler(self.__call + defines + [noLink, output, '-I{}'.format(include_path), source_file.filename()])
                        conn.send(True)
                        needsResult = conn.recv()
                        if not needsResult:
                            return
                        conn.send((retcode, stdout, stderr))
                        if retcode == 0:
                            send_file(object_file)
                        shutil.rmtree(include_path, ignore_errors=True)
        if task == "PREPROCESSED":
            with receive_compressed_file() as preprocessed_file:
                with TempFile(suffix='.obj') as object_file:
                    noLink = self.__compile_switch
                    output = self.__output_switch.format(object_file.filename())
                    retcode, stdout, stderr = compiler(self.__call + [noLink, output, preprocessed_file.filename()])
                    conn.send(True)
                    needsResult = conn.recv()
                    if not needsResult:
                        return
                    conn.send((retcode, stdout, stderr))
                    if retcode == 0:
                        send_file(object_file)
