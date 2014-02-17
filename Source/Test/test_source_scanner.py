import preprocessing
import threading
import os
from time import sleep

def collect_headers(filename, includes=[], defines=[],
        sysincludes=[], ignored_headers=[]):
    cache = preprocessing.Cache()
    preprocessor = preprocessing.Preprocessor(cache)
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
    return preprocessor.scan_headers(ppc, filename)

class Environment:
    def __init__(self, dir):
        self.dir = str(dir)

    def make_file(self, filename, content = ''):
        real_path = os.path.join(self.dir, filename)
        dirs = os.path.dirname(real_path)
        if not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        with open(real_path, 'wt') as file:
            file.write(content)

    def run(self, filename, includes=[], defines=[]):
        return set(x[0] for dir, headers in collect_headers(
            os.path.join(self.dir, filename),
            includes=[os.path.join(self.dir, i) for i in includes],
            defines=defines) for x in headers)

    def full_path(self, filename):
        return os.path.join(self.dir, filename)

    def touch(self, filename):
        # File change resolution is currently 1 sec.
        # Update modified time, so we are sure preprocessor detected change.
        filename = self.full_path(filename)
        statinfo = os.stat(filename)
        os.utime(filename, times=(statinfo.st_atime, statinfo.st_mtime + 1))



def test_simple(tmpdir):
    env = Environment(tmpdir)
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

def test_macros(tmpdir):
    env = Environment(tmpdir)
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

def test_header_guard(tmpdir):
    env = Environment(tmpdir)
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

def test_pragma_once(tmpdir):
    env = Environment(tmpdir)
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

def test_cache_stat(tmpdir):
    env = Environment(tmpdir)
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

def test_cache_stat_indirect(tmpdir):
    env = Environment(tmpdir)
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



