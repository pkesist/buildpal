#! python3
from utils import TempFile

import header_scanner

import copy
import itertools
import os
import sys
import types
import time
import zipfile


def collect_headers(cpp_file, rel_dir, search_path, defines):
    try:
        file = os.path.join(rel_dir, cpp_file)
        scanner = header_scanner.HeaderScanner(file)
        for path in search_path:
            scanner.add_include_path(path)
        for define in defines:
            define = define.split('=')
            assert len(define) == 1 or len(define) == 2
            macro = define[0]
            value = define[1] if len(define) == 2 else ""
            scanner.add_macro(macro, value)
        zip_file = TempFile(suffix='.zip')
        with zipfile.ZipFile(zip_file.filename(), 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for file, full in scanner.scan_headers():
                zip.write(full, file)
        return zip_file
    except:
        import traceback
        traceback.print_exc()

    # We failed to collect headers.
    return None

def test(header, search_path):
    import tempfile
    import shutil
    import subprocess
    import zipfile

    path, file = os.path.split(header)
    zip_file = collect_headers(file, path, search_path, [])
    include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
    with zipfile.ZipFile(zip_file.filename(), 'r') as zip:
        zip.extractall(path=include_path)
    import subprocess
    subprocess.check_call(r'"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\vcvarsall.bat" && cl -c -nologo /TP "{}" -I"{}"'.format(header, include_path), shell=True)
    shutil.rmtree(include_path)

if __name__ == '__main__':
    import sys
    boost_inc_path = [r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0']
    if sys.argv[1] == '1': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\mpl\or.hpp', boost_inc_path)
    if sys.argv[1] == '2': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\type_traits\detail\is_function_ptr_helper.hpp', boost_inc_path)
    if sys.argv[1] == '3': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\utility\result_of.hpp', boost_inc_path)
    if sys.argv[1] == '4': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\phoenix.hpp', boost_inc_path)
    if sys.argv[1] == '5': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\fusion\container\vector\vector10.hpp', boost_inc_path)
    if sys.argv[1] == '6': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\mpl\apply_wrap.hpp', boost_inc_path)
    if sys.argv[1] == 'x': test(r'D:\Sandboxes\PKE\DistriBuild\Source\gaga.cpp', boost_inc_path)

