import os
import subprocess
import tempfile
import zlib

class TempFile:
    """
        A more useful tempfile object which allows multiple open/close calls.
    """
    class Opener:
        def __init__(self, filename, mode):
            self.__filename = filename
            self.__file = open(filename, mode)
        
        def __enter__(self):
            return self.__file

        def __exit__(self, exc_type, exc_value, traceback):
            self.__file.close()

    def __init__(self, *args, **kwargs):
        file, filename = tempfile.mkstemp(*args, **kwargs)
        os.close(file)
        self.__filename = filename

    def open(self, mode):
        return TempFile.Opener(self.__filename, mode)

    def filename(self):
        return self.__filename

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.__filename)
        except:
            pass


def get_batch_file_environment_side_effects(batch, args):
    """
        Returns a dictionary containing side-effects made by the given batch
        file.
    """
    delimiter = "TEMP_FILE_TESTER_DELIMITER_1351361363416436"
    test_batch_name = None
    with TempFile(suffix=".bat") as test_batch:
        with test_batch.open('wt') as test_batch_file:
            test_batch_file.write("""
@echo off
echo {batch}
echo {delimiter}
set
echo {delimiter}
call "{batch}" {args}
echo {delimiter}
set
echo {delimiter}
""".format(batch=os.path.join(os.getcwd(), batch), args=" ".join(a for a in args), delimiter=delimiter))
        to_add={}
        with subprocess.Popen(test_batch.filename(), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            stdout, stderr = proc.communicate()
            output = stdout.decode()
            output = output.split('\r\n')
            first = output.index(delimiter)
            second = output.index(delimiter, first + 1)
            third  = output.index(delimiter, second + 1)
            fourth = output.index(delimiter, third + 1)
        
            before = output[first + 1 : second - 1]
            after  = output[third + 1 : fourth - 1]
            added = [a for a in after if not a in before]
            removed = [b for b in before if not b in after]
            for a in added:
                eq = a.index('=')
                to_add[a[:eq].upper()] = a[eq+1:]
        return to_add



def receive_file(conn, *args, **kwargs):
    tempfile = TempFile(*args, **kwargs)
    with tempfile.open('wb') as file:
        more = True
        while more:
            more, data = conn.recv()
            file.write(data)
    return tempfile

def receive_compressed_file(conn, *args, **kwargs):
    more = True
    tempfile = TempFile(*args, **kwargs)
    decompressor = zlib.decompressobj()
    with tempfile.open('wb') as file:
        while more:
            more, data = conn.recv()
            file.write(decompressor.decompress(data))
        file.write(decompressor.flush())
    return tempfile

def send_file(conn, file):
    for data in iter(lambda : file.read(10 * 1024), b''):
        conn.send((True, data))
    conn.send((False, b''))
