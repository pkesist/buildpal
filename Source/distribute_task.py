import os
import subprocess
import sys
import zlib

from utils import TempFile
from multiprocessing.connection import Client

class Task:
    def __init__(self):
        self.__completed = False

    def completed(self):
        return self.__completed

    def complete(self):
        self.__completed = True

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

    def call(self):
        return self.__call

    def type(self):
        return self.__type

    def send_receive(self, conn, lock, endpoint):
        with open(self.__input, "rb") as file:
            total = 0
            compr = 0
            compressor = zlib.compressobj(1)
            data = file.read(10 * 1024)
            total += len(data)
            while data:
                compressed = compressor.compress(data)
                compr += len(compressed)
                conn.send((True, compressed))
                data = file.read(10 * 1024)
                total += len(data)
            compressed = compressor.flush(zlib.Z_FINISH)
            compr += len(compressed)
            conn.send((False, compressed))

        done = conn.recv()
        with lock:
            if done:
                if self.completed():
                    conn.send(False)
                    return
            self.complete()
            conn.send(True)

        client_conn = Client(r"\\.\pipe\{}".format(endpoint), b"")
        retcode, stdout, stderr = conn.recv()
        client_conn.send((retcode, stdout, stderr))
        if retcode == 0:
            more = True
            with open(self.__output, "wb") as file:
                while more:
                    more, data = conn.recv()
                    file.write(data)
            client_conn.send(True)

    def process(self, server, conn):
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
                data = file.read(4096)
                while data:
                    conn.send((True, data))
                    data = file.read(4096)
                conn.send((False, data))

        try:
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
        except:
            import traceback
            traceback.print_exc()
            raise
