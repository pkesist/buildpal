import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
import io

from utils import TempFile, send_file, receive_file, receive_compressed_file, send_compressed_file
from multiprocessing.connection import Client

class CompileTask:
    def __init__(self, cwd, call, source, source_type, preprocessor_info, output, compiler_info, pch_file, pch_header, distributer):
        self.__cwd = cwd
        self.__call = call
        self.__source_type = source_type
        self.__preprocessor_info = preprocessor_info
        self.__compiler_info = compiler_info
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()
        self.__pch_file = pch_file
        self.__pch_header = pch_header
        self.output = output
        self.source = source
        self.tempfile = None

        self.algorithm = 'SCAN_HEADERS'
        #self.algorithm = 'PREPROCESS_LOCALLY_WITH_BUILTIN_PREPROCESSOR'
        #self.algorithm = 'PREPROCESS_LOCALLY'

    def manager_prepare(self):
        macros = self.__preprocessor_info.macros + self.__preprocessor_info.builtin_macros
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
        return collect_headers(os.path.join(self.__cwd, self.source),
            self.__preprocessor_info.includes, [], macros,
            [self.__pch_header] if self.__pch_header else [],
            self.__compiler_info)

    def manager_send(self, client_conn, server_conn):
        if self.algorithm == 'SCAN_HEADERS':
            server_conn.send('SCAN_HEADERS')
            server_conn.send('ZIP_FILE')
            with open(self.tempfile, 'rb') as file:
                send_file(server_conn, file)
            server_conn.send('SOURCE_FILE')
            with open(os.path.join(self.__cwd, self.source), 'rb') as cpp:
                send_file(server_conn, cpp)
            if self.__pch_file:
                server_conn.send('NEED_PCH_FILE')
                response = server_conn.recv()
                if response:
                    with open(os.path.join(os.getcwd(), self.__pch_file[0]), 'rb') as pch_file:
                        send_compressed_file(server_conn, pch_file)

        if self.algorithm == 'PREPROCESS_LOCALLY':
            server_conn.send('PREPROCESS_LOCALLY')
            # Signal the client to do preprocessing.
            client_conn.send('PREPROCESS')
            server_conn.send('PREPROCESSED_FILE')
            relay_file(client_conn, server_conn)

        if self.algorithm == 'PREPROCESS_LOCALLY_WITH_BUILTIN_PREPROCESSOR':
            server_conn.send('PREPROCESS_LOCALLY')
            from scan_headers import preprocess_file
            macros = self.__preprocessor_info.macros + self.__preprocessor_info.builtin_macros
            preprocessed_data = preprocess_file(
                os.path.join(self.__cwd, self.source),
                self.__preprocessor_info.includes,
                self.__preprocessor_info.sysincludes,
                macros, self.__compiler_info)
            send_compressed_file(server_conn, io.BytesIO(preprocessed_data))

    def manager_receive(self, client_conn, server_conn):
        retcode, stdout, stderr = server_conn.recv()
        if retcode == 0:
            length = 0
            more = True
            with open(self.output, "wb") as file:
                receive_compressed_file(server_conn, file)
        client_conn.send('COMPLETED')
        client_conn.send((retcode, stdout, stderr))
        return True

    def server_process(self, server, conn, remote_endpoint):
        accept = server.accept()
        compiler = server.setup_compiler(self.__compiler_info)
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        algorithm = conn.recv()
        if algorithm == 'SCAN_HEADERS':
            text = conn.recv()
            assert text == 'ZIP_FILE'
            with receive_file(conn) as zip_file:
                include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
                with zipfile.ZipFile(zip_file.filename(), 'r') as zip:
                    zip.extractall(path=include_path)
                include_dirs = [include_path]

                include_list = os.path.join(include_path, 'include_paths.txt')
                if os.path.exists(include_list):
                    for path in open(include_list, 'rt'):
                        assert not os.path.isabs(path)
                        include_dirs.append(os.path.normpath(os.path.join(include_path, path)))
                try:
                    task = conn.recv()
                    assert task == 'SOURCE_FILE'
                    with receive_file(conn, suffix=self.__source_type) as source_file, TempFile(suffix='.obj') as object_file:
                        if self.__pch_file:
                            task = conn.recv()
                            assert task == 'NEED_PCH_FILE'
                            
                            try:
                                server.file_repository().acquire()
                                local_file = server.file_repository().check_file(*self.__pch_file)
                                if local_file is None:
                                    conn.send(True)
                                    local_file = server.file_repository().register_file(*self.__pch_file)
                                    with open(local_file, 'wb') as pch_file:
                                        receive_compressed_file(conn, pch_file)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     
                                else:
                                    conn.send(False)
                            finally:
                                server.file_repository().release()
                        noLink = self.__compile_switch
                        output = self.__output_switch.format(object_file.filename())

                        # FIXME - remove hardcoded switches, use compiler_info
                        defines = ['-D{}'.format(define) for define in self.__preprocessor_info.macros]
                        pch_switch = []
                        if self.__pch_file:
                            assert local_file is not None
                            assert os.path.exists(local_file)
                            pch_switch.append('-Fp{}'.format(local_file))

                        try:
                            command = (self.__call + defines + pch_switch +
                                [noLink, output] +
                                ['-I{}'.format(incpath) for incpath in include_dirs] +
                                [source_file.filename()])
                            retcode, stdout, stderr = compiler(command)
                        except Exception:
                            conn.send('SERVER_FAILED')
                            return
                        conn.send('SERVER_DONE')
                        needsResult = conn.recv()
                        if not needsResult:
                            return
                        conn.send((retcode, stdout, stderr))
                        if retcode == 0:
                            with object_file.open('rb') as obj:
                                send_compressed_file(conn, obj)
                finally:
                    shutil.rmtree(include_path, ignore_errors=True)

        if algorithm == 'PREPROCESS_LOCALLY':
            tmp = TempFile()
            text = conn.recv()
            assert text == 'PREPROCESSED_FILE'
            with tmp.open('wb') as temp:
                receive_compressed_file(conn, temp)

            with tmp as preprocessed_file, TempFile(suffix='.obj') as object_file:
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
                    with object_file.open('rb') as obj:
                        send_compressed_file(conn, obj)
