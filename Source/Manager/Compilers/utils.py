import subprocess
import os

def get_batch_file_environment_side_effects(batch, args):
    """
        Returns a dictionary containing side-effects made by the given batch
        file.
    """
    delimiter = "TEMP_FILE_TESTER_DELIMITER_1351361363416436"
    test_batch_name = None
    fd, test_batch_filename = tempfile.mkstemp(suffix='.bat')
    with os.fdopen(fd, 'wt') as test_batch:
        test_batch.write("""
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
    with subprocess.Popen(test_batch_filename, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
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
    os.path.remove(test_batch_filename)
    return to_add
