from Manager import collect_headers
import os

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
        return set(x[1] for x in collect_headers(
            self.dir,
            filename,
            [os.path.join(self.dir, i) for i in includes],
            [], defines))

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

def test_header_guard(tmpdir, dump):
    env = Environment(tmpdir)
    env.make_file('aaa/a.h')
    env.make_file('aaa/x.h', '''
#ifndef X_H
#define X_H
#include "a.h"
#endif
''')
    env.make_file('aaa/y.h', '''
#ifndef Y_H
#define Y_H
#include "x.h"
#endif
''')
    env.make_file('aaa/z.h', '''
#ifndef Z_H
#define Z_H
#include "x.h"
#endif
''')
    env.make_file('test.cpp', '''
#include "y.h"
#include "z.h"
#include "a.h"
''')
    assert env.run('test.cpp', includes=['aaa']) == \
        {'a.h', 'x.h', 'y.h', 'z.h'}

    env.make_file('test2.cpp', '''
#include "x.h"
''')
    assert env.run('test2.cpp', includes=['aaa']) == \
        {'a.h', 'x.h'}
