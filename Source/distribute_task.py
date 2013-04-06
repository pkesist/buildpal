import os
import subprocess
import sys
import tempfile
import zlib

class Task:
    pass

class CompileTask(Task):
    def __init__(self, call, source, source_type, input, output, distributer):
        self.__call = call
        self.__source = source
        self.__input = input
        self.__source_type = source_type
        self.__output = output
        self.__output_switch = distributer.object_name_option().make_value('{}').make_str()
        self.__compile_switch = distributer.compile_no_link_option().make_value().make_str()

    def accept(self):
        return True

    def call(self):
        return self.__call

    def type(self):
        return self.__type

    def accepted(self, conn):
        total = 0
        compr = 0
        compressor = zlib.compressobj(1)
        with open(self.__input, 'rb') as file:
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

    def complete(self, conn):
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
            local_call = self.__call + [noLink, output, file]
            with subprocess.Popen(local_call, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                output = proc.communicate()
                conn.send((proc.returncode, output[0], output[1],))
            if proc.returncode == 0:
                os.remove(file)
                send_file(objectFilename)
                os.remove(objectFilename)
        except:
            import traceback
            traceback.print_exc()
            raise


