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
import threading

from tempfile import mkdtemp
from shutil import rmtree

cache = preprocessing.Cache()
thread_local = threading.local()

def setup_preprocessor(includes, sysincludes, defines, ignored_headers=[]):
    if not hasattr(thread_local, 'preprocessor'):
        thread_local.preprocessor = preprocessing.Preprocessor(cache)
    preprocessor = thread_local.preprocessor
    preprocessor.setMicrosoftMode(True) # If MSVC.
    preprocessor.setMicrosoftExt(True) # Should depend on Ze & Za compiler options.
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
    for ignored_header in ignored_headers:
        ppc.add_ignored_header(ignored_header)
    return preprocessor, ppc

def create_pth(hpp_file, pth_file, includes, sysincludes, defines):
    preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines)
    with TempFile(suffix='.cpp') as cpp:
        with cpp.open('wt') as cpp_file:
            cpp_file.write('#include "{}"\n'.format(hpp_file))
        preprocessor.emitPTH(ppc, cpp.filename(), pth_file)
    return pth_file

def preprocess_file(cpp_file, includes, sysincludes, defines):
    try:
        preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines)
        return preprocessor.preprocess(ppc, cpp_file)
    except Exception:
        import traceback
        traceback.print_exc()

    # We failed to collect headers.
    return None

def all_headers(cpp_file, includes, sysincludes, defines, pth_file, ignored_headers=[]):
    preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines, ignored_headers)
    return preprocessor.scanHeaders(ppc, cpp_file, pth_file)


def collect_headers(cpp_file, includes, sysincludes, defines, pth_file, ignored_headers=[]):
    try:
        preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines, ignored_headers)
        zip_file = TempFile(suffix='.zip')
        paths_to_include = []
        relative_paths = {}
        with zipfile.ZipFile(zip_file.filename(), 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for file, full in preprocessor.scanHeaders(ppc, cpp_file, pth_file):
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

def rewrite_includes(cpp_file, includes, sysincludes, defines, pth_file):
    try:
        includes = list(a.replace('\\', '/') for a in includes)
        sysincludes = list(a.replace('\\', '/') for a in sysincludes)
        ppc = setup_preprocessor(includes, sysincludes, defines)
        return preprocessor.rewriteIncludes(ppc, cpp_file)
    except:
        import traceback
        traceback.print_exc()

    # We failed to rewrite includes.
    return None


def test1():
    include = mkdtemp()
    with TempFile(dir=include, suffix='.cpp') as f1, \
        TempFile(dir=include, suffix='.hpp') as f2:
        f2rel = os.path.split(f2.filename())[1]
        with f1.open('wt') as file1:
            file1.write("""\
#ifndef FILE1
#define FILE1 aaa
#include <{}>
#endif
""".format(f2rel))
        with f2.open('wt') as file2:
            file2.write("""\
#define XXX 5
""")
        result = all_headers(f1.filename(), [include], [], [], "")
        rmtree(include)
        assert len(result) == 1
        assert (f2rel, f2.filename()) in result

def test2():
    include = mkdtemp()
    with TempFile(dir=include, suffix='.cpp') as f1, \
        TempFile(dir=include, suffix='.hpp') as f2, \
        TempFile(dir=include, suffix='.hpp') as f3:
        f2rel = os.path.split(f2.filename())[1]
        f3rel = os.path.split(f3.filename())[1]
        with f1.open('wt') as file1:
            file1.write("""\
#ifndef FILE1
#define FILE1
#include <{0}>
#include <{0}>
#endif
""".format(f2rel))
        with f2.open('wt') as file2:
            file2.write("""\
#ifndef XXX
#define XXX
#else
#include <{}>
#endif
""".format(f3rel))
        with f3.open('wt') as file3:
            file3.write("""\
#define ZZZ
""")
        result = all_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert (f2rel, f2.filename()) in result
        assert (f3rel, f3.filename()) in result
        result = all_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert (f2rel, f2.filename()) in result
        assert (f3rel, f3.filename()) in result
        rmtree(include)


def test_boost_header(header, boostdir):
    from time import time
    start = time()    
    all_headers(header, [boostdir], [], [], "")
    first_done = time()
    all_headers(header, [boostdir], [], [], "")
    second_done = time()
    all_headers(header, [boostdir], [], [], "")
    third_done = time()
    print("First time took {:.2f}s, second time took {:.2f}s, third time took {:.2f}s."
          .format(first_done - start, second_done - first_done, third_done - second_done))

def test_files(files, includes, macros):
    for file in files:
        print("FILE ", file)
        start = time.time()
        for x in all_headers(file, includes, [], macros, ""):
            if 'boost/function' in x[0]:
                print(x[0])
        print("It took {:.2f}s.".format(time.time() - start))

if __name__ == '__main__':
    #test_boost_header(
    #    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\phoenix\phoenix.hpp",
    ##    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\math\src\tr1\assoc_laguerre.cpp",
    #    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0")
    #test_boost_header(
    ##    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\phoenix\phoenix.hpp",
    #    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\math\src\tr1\assoc_laguerre.cpp",
    #    r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0")
    #print(all_headers(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\thread\src\win32\thread.cpp',
    #            [r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0"], [], [], ""))
    test_files([
        r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\thread\src\win32\thread.cpp'
        ],
        [r"D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0"],
        ['_MSC_VER=1500',
        '_MSC_FULL_VER=150030729',
        '_CPPLIB_VER=505',
        '_HAS_TR1=1',
        '_WIN32=1',
        '_M_IX86=600',
        '_INTEGRAL_MAX_BITS=64',
        '__cplusplus=199711L',
        '_CPPUNWIND=1'])
    print("We are done!")
    input()
    #test1()
    #test2()
