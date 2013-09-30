#! python3.3
from io import BytesIO, RawIOBase
from utils import TempFile

import preprocessing

import copy
import itertools
import os
import sys
import types
import time
import tarfile
import threading

from tempfile import mkdtemp
from shutil import rmtree

cache = preprocessing.Cache()
preprocessor = preprocessing.Preprocessor(cache)

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

def all_headers(cpp_file, includes, sysincludes, defines, ignored_headers=[]):
    preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines, ignored_headers)
    return preprocessor.scanHeaders(ppc, cpp_file)

def collect_headers(cwd, rel_file, includes, sysincludes, defines, ignored_headers=[]):
    cpp_file = os.path.join(cwd, rel_file)

    def write_str_to_tar(tar, name, content, header=b''):
        info = tarfile.TarInfo(name=name)
        info.size = len(content)
        if header:
            info.size += len(header)
        tar.addfile(info)
        tar.fileobj.write(header)
        tar.fileobj.write(content)
        blocks, remainder = divmod(info.size, tarfile.BLOCKSIZE)
        if remainder:
            tar.fileobj.write(tarfile.NUL * (tarfile.BLOCKSIZE - remainder))
            blocks += 1
        tar.offset += blocks * tarfile.BLOCKSIZE

    try:
        preprocessor, ppc = setup_preprocessor(includes, sysincludes, defines, ignored_headers)
        paths_to_include = []
        relative_paths = {}
        tarBuffer = BytesIO()
        with tarfile.open(mode='w:bz2', fileobj=tarBuffer) as tar:
            for file, abs, content in preprocessor.scanHeaders(ppc, cpp_file):
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
                        write_str_to_tar(tar, relative_paths[depth] + 'dummy', b"Dummy file needed to create directory structure")
                write_str_to_tar(tar, '/'.join(path_elements), content, '#line 1 "{}"\r\n'.format(os.path.normpath(abs)).replace('\\', '\\\\').encode())
            if paths_to_include:
                write_str_to_tar(tar, 'include_paths.txt', "\n".join(paths_to_include).encode())
            tar.add(cpp_file, rel_file, '#line 1 "{}"\r\n'.format(os.path.normpath(cpp_file).replace('\\', '\\\\').encode()))
        hits, misses = cache.getStats()
        total = hits + misses
        print("{} hits, {} misses, hit ratio {:0>1.2f}".format(hits, misses, 0 if total == 0 else hits/total))
        tarBuffer.seek(0)
        return tarBuffer
    except Exception:
        import traceback
        traceback.print_exc()

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
        result = all_headers(f1.filename(), [include], [], [], "")
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
        result = all_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert result[0][:2] == (f2rel, f2.filename())
        assert result[1][:2] == (f3rel, f3.filename())
        result = all_headers(f1.filename(), [include], [], [], "")
        assert len(result) == 2
        assert result[0][:2] == (f2rel, f2.filename())
        assert result[1][:2] == (f3rel, f3.filename())
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
