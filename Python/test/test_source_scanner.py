import preprocessing
import pytest
import threading
import os
from time import sleep
import codecs

class Environment:
    def __init__(self, dir):
        self.dir = str(dir)

    def make_file(self, filename, content = ''):
        real_path = os.path.join(self.dir, filename)
        dirs = os.path.dirname(real_path)
        if not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        openmode = 'wb' if type(content) == bytes else 'wt'
        with open(real_path, openmode) as file:
            file.write(content)

    @staticmethod
    def collect_headers(filename, includes=[], defines=[],
            sysincludes=[], use_cache=True):
        preprocessor = preprocessing.Preprocessor(preprocessing.Cache() if use_cache else None)
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
        return preprocessor.scan_headers(ppc, filename)

    def run_worker(self, filename, includes=[], defines=[], use_cache=False):
        header_data, missing_headers = Environment.collect_headers(
            os.path.join(self.dir, filename),
            includes=[os.path.join(self.dir, i) for i in includes],
            defines=defines, use_cache=use_cache)
        return set(x[0] for dir, headers in header_data for x in headers)

    def run_nocache(self, filename, includes=[], defines=[]):
        return self.run_worker(filename, includes, defines, use_cache=False)

    def run_withcache(self, filename, includes=[], defines=[]):
        return self.run_worker(filename, includes, defines, use_cache=True)

    def full_path(self, filename):
        return os.path.join(self.dir, filename)

    def touch(self, filename):
        # File change resolution is currently 1 sec.
        # Update modified time, so we are sure preprocessor detected change.
        filename = self.full_path(filename)
        statinfo = os.stat(filename)
        os.utime(filename, times=(statinfo.st_atime, statinfo.st_mtime + 1))

@pytest.fixture(params=["run_withcache", "run_nocache"])
def env(request, tmpdir):
    env = Environment(tmpdir)
    env.run = getattr(env, request.param)
    return env

def test_simple(env):
    env.make_file('a.h')
    env.make_file('test1.cpp', r'''
#include "a.h"
''')
    assert env.run('test1.cpp') == {'a.h'}

    env.make_file('test2.cpp', r'''
#include <a.h>
''')
    assert not env.run('test2.cpp')
    assert env.run('test2.cpp', includes=['.']) == {'a.h'}

def test_macros(env):
    env.make_file('a.h')
    env.make_file('test1.cpp', r'''
#define XXX "a.h"
#include XXX
''')
    assert env.run('test1.cpp') == {'a.h'}

    env.make_file('test2.cpp', r'''
#define STR(x) STR_2(x)
#define STR_2(x) #x
#define XXX a.h
#include STR(XXX)
''')
    assert env.run('test1.cpp') == {'a.h'}

def test_header_guard(env):
    env.make_file('aaa/a.h')
    env.make_file('aaa/x.h', '''
#if !defined(X_H)
#define X_H
#include "a.h"
#endif
''')
    env.make_file('test.cpp', '''
#include "x.h"
#include "x.h"
''')
    assert env.run('test.cpp', includes=['aaa']) == \
        {'a.h', 'x.h'}

    env.make_file('test2.cpp', '''
#include "x.h"
''')
    assert env.run('test2.cpp', includes=['aaa']) == \
        {'a.h', 'x.h'}

def test_pragma_once(env):
    env.make_file('xxx.h')
    env.make_file('yyy.h')
    env.make_file('a.h', '''
#ifdef USE_PRAGMA_ONCE
#pragma once
#endif
#ifndef XXX
#define XXX
#else
#define YYY
#endif
''')
    env.make_file('test.cpp', '''
#include "a.h"
#include "a.h"
#ifdef XXX
#include "xxx.h"
#endif
#ifdef YYY
#include "yyy.h"
#endif
''')

    assert env.run('test.cpp', defines=['USE_PRAGMA_ONCE=1']) \
            == {'a.h', 'xxx.h'}
    assert env.run('test.cpp') == {'a.h', 'xxx.h', 'yyy.h'}

    # Run it again, to make sure cache works
    assert env.run('test.cpp', defines=['USE_PRAGMA_ONCE=1']) \
            == {'a.h', 'xxx.h'}
    assert env.run('test.cpp') == {'a.h', 'xxx.h', 'yyy.h'}

    env.make_file('test2.cpp', '''
#define XXX
#include "a.h"
#ifdef YYY
#include "yyy.h"
#endif
''')
    assert env.run('test2.cpp', defines=['USE_PRAGMA_ONCE=1']) \
        == {'a.h', 'yyy.h'}
    assert env.run('test2.cpp') == {'a.h', 'yyy.h'}

def test_cache_stat(env):
    env.make_file('xxx.h')
    env.make_file('yyy.h')
    env.make_file('a.h', '''
#include "xxx.h"
''')
    env.make_file('test.cpp', '''
#include "a.h"
''')
    assert env.run('test.cpp') == {'a.h', 'xxx.h'}

    env.make_file('a.h', '''
#include "yyy.h"
''')

    env.touch('a.h')
    assert env.run('test.cpp') == {'a.h', 'yyy.h'}

def test_cache_stat_indirect(env):
    env.make_file('xxx.h')
    env.make_file('yyy.h')
    env.make_file('a.h', '''
#include "xxx.h"
''')

    env.make_file('zozo.h', '''
#include "a.h"
''')

    env.make_file('test2.cpp', '''
#include "zozo.h"
''')

    assert env.run('test2.cpp') == {'zozo.h', 'a.h', 'xxx.h'}
    env.make_file('a.h', '''
#include "yyy.h"
''')
    env.touch('a.h')
    assert env.run('test2.cpp') == {'zozo.h', 'a.h', 'yyy.h'}


def test_leakage(env):
    import gc
    env.make_file('xxx.h', 'SOME SIGNIFICANTLY LONG CONTENT' * 10 * 1024)
    env.make_file('a.cpp', '#include "xxx.h"\n')

    memviews = len(list(None for x in gc.get_objects() if type(x) == memoryview))
    for x in range(16):
        env.run('a.cpp')
    memviews2 = len(list(None for x in gc.get_objects() if type(x) == memoryview))
    assert memviews == memviews2

def test_rel_include(env):
    env.make_file('xxx\\dodo.h')
    env.make_file('xxx\\bbb.h', '''#include "dodo.h"''')
    env.make_file('testme.cpp', '''#include "xxx/bbb.h"''')
    assert env.run('testme.cpp') == {'xxx/dodo.h', 'xxx/bbb.h'}

def test_uft16_le_src(env):
    env.make_file('dodo.h')
    env.make_file('ima_utf16le_file.cpp',
        codecs.BOM_UTF16_LE + '#include "dodo.h"\n'.encode('utf-16-le'))
    assert env.run('ima_utf16le_file.cpp') == {'dodo.h'}

def test_uft16_be_src(env):
    env.make_file('dodo.h')
    env.make_file('ima_utf16be_file.cpp',
        codecs.BOM_UTF16_BE + '#include "dodo.h"\n'.encode('utf-16-be'))
    assert env.run('ima_utf16be_file.cpp') == {'dodo.h'}
