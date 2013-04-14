import os
import subprocess
import sys
import zlib

from utils import TempFile
from multiprocessing.connection import Client

class Task:
    pass

class CompileTask(Task):
    def __init__(self, call, source, source_type, input, output, compiler_info, distributer):
        super(CompileTask, self).__init__()
        self.__compiler_info = compiler_info
        self.__call = call
        self.__source = source
        self.__input = input
        self.__source_type = source_type
        self.__output = output
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()

    def manager_send(self, server_conn, client_conn, wrapped_task):
        with open(self.__input, "rb") as file:
            for data in iter(lambda : file.read(10 * 1024), b''):
                server_conn.send((True, data))
            server_conn.send((False, b''))

    def manager_receive(self, server_conn, client_conn, wrapped_task):
        retcode, stdout, stderr = server_conn.recv()
        client_conn.send((retcode, stdout, stderr))
        if retcode == 0:
            more = True
            with open(self.__output, "wb") as file:
                while more:
                    more, data = server_conn.recv()
                    file.write(data)
            client_conn.send(True)
        return True

    def server_process(self, server, conn):
        accept = server.accept()
        compiler = server.setup_compiler(self.__compiler_info)
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        def receive_file():
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

        with receive_file() as preprocessed_file:
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
