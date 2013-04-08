import os
import subprocess
import sys
import tempfile
import zlib
import psutil

class Task:
    pass

class CompileTask(Task):
    def __init__(self, call, source, source_type, input, output, compiler_info, distributer):
        self.__compiler_info = compiler_info
        self.__call = call
        self.__source = source
        self.__input = input
        self.__source_type = source_type
        self.__output = output
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()

    def accept(self):
        # Accept task if we have at least 50% of one processor.
        usage = psutil.cpu_percent(percpu=True)
        count = len(usage)
        return count * 100 - sum(usage) >= 50

    def call(self):
        return self.__call

    def type(self):
        return self.__type

    def send_receive(self, conn):
        input = self.__input()
        if callable(input):
            input = input()
        total = 0
        compr = 0
        compressor = zlib.compressobj(1)
        with open(input, 'rb') as file:
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
        try:
            os.remove(self.__input)
        except:
            pass

        retcode, stdout, stderr = conn.recv()
        sys.stdout.write(stdout.decode())
        if stderr:
            sys.stderr.write("---------------------------- STDERR ----------------------------\n")
            sys.stderr.write(stderr.decode())
            sys.stderr.write("----------------------------------------------------------------\n")
        if retcode == 0:
            more = True
            with open(self.__output, "wb") as file:
                while more:
                    more, data = conn.recv()
                    file.write(data)
            return True
        return False

    def setup_compiler(self):
        if self.__compiler_info.toolset() == 'msvc':
            import msvc
            return msvc.MSVCDistributer.setup_compiler(self.__compiler_info)
        else:
            raise RuntimeError("Unknown toolset '{}'".format(self.__compiler_info.toolset()))

    def process(self, conn):
        accept = self.accept()
        compiler = self.setup_compiler()
        conn.send((accept, compiler is not None))
        if not accept or compiler is None:
            return

        def receive_file():
            more = True
            fileDesc, filename = tempfile.mkstemp(suffix="{}".format(self.__source_type))
            decompressor = zlib.decompressobj()
            with os.fdopen(fileDesc, "wb") as file:
                while more:
                    more, data = conn.recv()
                    file.write(decompressor.decompress(data))
                file.write(decompressor.flush())
            return filename

        def send_file(name):
            with open(name, "rb") as file:
                data = file.read(4096)
                while data:
                    conn.send((True, data))
                    data = file.read(4096)
                conn.send((False, data))

        file = receive_file()
        
        try:
            fileDesc, objectFilename = tempfile.mkstemp(suffix=".obj")
            os.close(fileDesc)
            noLink = self.__compile_switch
            output = self.__output_switch.format(objectFilename)
            retcode, stdout, stderr = compiler(self.__call + [noLink, output, file])
            conn.send((retcode, stdout, stderr,))
            if retcode == 0:
                os.remove(file)
                send_file(objectFilename)
                os.remove(objectFilename)
        except:
            import traceback
            traceback.print_exc()
            raise
