#! python3.3
from utils import TempFile

import preprocessing

import copy
import itertools
import os
import sys
import types
import time
import zipfile


preprocessor = preprocessing.Preprocessor()

def setup_preprocessor():
    preprocessor.setMicrosoftMode(True) # If MSVC.
    preprocessor.setMicrosoftExt(True) # Should depend on Ze & Za compiler options.

def preprocess_file(cpp_file, includes, sysincludes, defines, compiler_info):
    try:
        setup_preprocessor()
        ppc = preprocessing.PreprocessingContext()
        for path in includes:
            ppc.add_include_path(path)
        for path in sysincludes:
            ppc.add_include_path(path, True)
        for define in defines:
            define = define.split('=')
            assert len(define) == 1 or len(define) == 2
            macro = define[0]
            value = define[1] if len(define) == 2 else ""
            ppc.add_macro(macro, value)
        return preprocessor.preprocess(ppc, cpp_file)
    except Exception:
        import traceback
        traceback.print_exc()

    # We failed to collect headers.
    return None


def collect_headers(cpp_file, includes, sysincludes, defines, headers_to_skip=[], compiler_info=None):
    try:
        setup_preprocessor()
        ppc = preprocessing.PreprocessingContext()
        for path in includes:
            ppc.add_include_path(path)
        for path in sysincludes:
            ppc.add_include_path(path, True)
        for define in defines:
            define = define.split('=')
            assert len(define) == 1 or len(define) == 2
            macro = define[0]
            value = define[1] if len(define) == 2 else ""
            ppc.add_macro(macro, value)
        zip_file = TempFile(suffix='.zip')
        paths_to_include = []
        relative_paths = {}
        with zipfile.ZipFile(zip_file.filename(), 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for file, full in preprocessor.scanHeaders(ppc, cpp_file, headers_to_skip):
                depth = 0
                path_elements = file.split('/')
                # Handle '.' in include directive.
                path_elements = [p for p in path_elements if p != '.']
                # Handle '..' in include directive.
                while '..' in path_elements:
                    index = path_elements.index('..')
                    if index == 0:
                        depth += 1
                        del path_elements[index]
                    else:
                        del path_element[index - 1:index + 1]
                if depth:
                    path_elements = ['_rel_includes'] + path_elements
                    if not depth in relative_paths:
                        # Add a dummy file which will create this structure.
                        relative_paths[depth] = '_rel_includes/' + 'rel/' * depth
                        paths_to_include.append(relative_paths[depth])
                        zip.writestr(relative_paths[depth] + 'dummy', "Dummy file needed to create directory structure")
                zip.write(full, '/'.join(path_elements))
            if paths_to_include:
                zip.writestr('include_paths.txt', "\n".join(paths_to_include))
        return zip_file.filename()
    except Exception:
        import traceback
        traceback.print_exc()

    # We failed to collect headers.
    return None

def test(header, search_path):
    import tempfile
    import shutil
    import subprocess
    import zipfile

    zip_file = collect_headers(header, search_path, [], [])
    include_path = tempfile.mkdtemp(suffix='', prefix='tmp', dir=None)
    with zipfile.ZipFile(zip_file, 'r') as zip:
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
    if sys.argv[1] == '7': test(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\locale\src\win32\collate.cpp', boost_inc_path)
    if sys.argv[1] == 'x': test(r'D:\Sandboxes\PKE\DistriBuild\Source\gaga.cpp', boost_inc_path)

