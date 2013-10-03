#! python3.3
from utils import TempFile

import preprocessing

import os
import sys
import types
import time

from tempfile import mkdtemp
from shutil import rmtree

preprocessor = preprocessing.Preprocessor(True)

def setup_preprocessor(includes, sysincludes, defines, ignored_headers=[]):
    preprocessor.setMicrosoftMode(True) # If MSVC.
    preprocessor.setMicrosoftExt(True) # Should depend on Ze & Za compiler options.
    ppc = preprocessing.PreprocessingContext()
    for path in includes:
        ppc.add_include_path(path, False)
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

def collect_headers(cpp_file, includes, sysincludes, defines, ignored_headers=[]):
    preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines, ignored_headers)
    return preprocessor.scanHeaders(ppc, cpp_file)

    # We failed to collect headers.
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
        result = collect_headers(f1.filename(), [include], [], [], "")
        rmtree(include)
        assert len(result) == 1
        assert result[:2] == (f2rel, f2.filename()) in result

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
        result = collect_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert result[0][:2] == (f2rel, f2.filename())
        assert result[1][:2] == (f3rel, f3.filename())
        result = collect_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert result[0][:2] == (f2rel, f2.filename())
        assert result[1][:2] == (f3rel, f3.filename())
        rmtree(include)


def test_boost_header(header, boostdir):
    from time import time
    start = time()
    collect_headers(header, [boostdir], [], [], "")
    first_done = time()
    collect_headers(header, [boostdir], [], [], "")
    second_done = time()
    collect_headers(header, [boostdir], [], [], "")
    third_done = time()
    print("First time took {:.2f}s, second time took {:.2f}s, third time took {:.2f}s."
          .format(first_done - start, second_done - first_done, third_done - second_done))

def test_files(files, includes, macros):
    for file in files:
        print("FILE ", file)
        start = time.time()
        for x in collect_headers(file, includes, [], macros, ""):
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
    #print(collect_headers(r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\libs\thread\src\win32\thread.cpp',
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
