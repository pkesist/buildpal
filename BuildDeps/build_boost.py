from .utils import get_zip

from distutils.cmd import Command
from distutils.spawn import find_executable
import distutils.ccompiler

import os
import subprocess
import sys
from multiprocessing import cpu_count

import zipfile

class build_boost(Command):
    description = "build Boost C++ libraries"

    user_options = [
        ('boost-version='  , None, 'Boost version used'),
        ('build-base='     , None, 'base directory for Boost build'),
        ('boost-build-dir=', None, 'directory where to build Boost'),
        ('compiler='       , None, 'Compiler'),
        ('boost-libs='     , None, 'Boost libraries to build'),
        ('debug'           , None, 'compile in debug mode'),
        ('x86'             , None, 'compile for x86 arch'),
        ('x64'             , None, 'compile for x64 arch')
    ]

    boolean_options = ['debug', 'x86', 'x64']

    def initialize_options(self):
        self.debug = None
        self.x86 = None
        self.x64 = None
        self.build_base = None
        self.compiler = None
        self.boost_version = None
        self.boost_build_dir = None
        self.boost_libs = ""

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'))
        self.set_undefined_options('build_ext',
            ('compiler', 'compiler'),
            ('debug', 'debug'))

        if not self.x64 and not self.x86:
            self.x64 = sys.maxsize > 2**32
            self.x86 = not self.x64

        if self.boost_version is None:
            self.boost_version = (1, 55, 0)
        else:
            self.boost_version = tuple(int(x) for x in
                self.boost_version.split('.'))

        if self.boost_libs:
            self.boost_libs = self.boost_libs.split(';')
        else:
            self.boost_libs = []
        if self.boost_build_dir is None:
            self.boost_build_dir = 'boost_{}_{}_{}'.format(*self.boost_version)
        self.boost_build_dir = os.path.join(self.build_base, self.boost_build_dir)

    def library_dir_x64(self):
        return os.path.join(self.boost_build_dir, 'x64', 'lib')

    def library_dir_x86(self):
        return os.path.join(self.boost_build_dir, 'lib')

    def libraries(self):
        return ['boost_{}'.format(lib) for lib in self.boost_libs]

    def run(self):
        assert self.compiler is not None
        if self.compiler == 'msvc':
            toolset='msvc-11.0'
        elif self.compiler == 'mingw32':
            toolset='gcc'
        
        if self.x86:
            self.__build_boost(self.boost_version, toolset, self.boost_build_dir,
                False, self.build_base)
        if self.x64:
            self.__build_boost(self.boost_version, toolset, self.boost_build_dir,
                True, self.build_base)
        
        #build_ext = self.get_finalized_command('build_ext')
        #build_ext.include_dirs.append(os.path.join(self.boost_build_dir))
        #build_ext.library_dirs.append(self.library_dir())
        #if toolset == 'gcc':
        #    build_ext.libraries.extend(self.libraries)

    def __build_boost(self, boost_version, toolset, build_dir, x64, cache_dir):
        url = "http://downloads.sourceforge.net/project/boost/boost/{0}.{1}.{2}/boost_{0}_{1}_{2}.zip".format(*boost_version)

        if not os.path.isdir(build_dir):
            get_zip(url, build_dir, cache_dir)
        else:
            print("Found '{}', assuming it contains Boost {}.{}.{}".format(build_dir, *boost_version))
        
        b2_exe = find_executable('b2', build_dir)
        if b2_exe is None:
            subprocess.check_call(['bootstrap.bat'], cwd=build_dir, shell=True)
            b2_exe = find_executable('b2', build_dir)
        
        if not self.boost_libs:
            return

        build_call = [b2_exe, '-j{}'.format(cpu_count()), 'stage',
            '--stagedir={}'.format('x64' if x64 else '.'),
            'toolset={}'.format(toolset), 'link=static',
            'runtime-link=shared', 'threading=multi']
        build_call.extend(('--with-{}'.format(lib) for lib in
            self.boost_libs))
        if x64:
            build_call.append('address-model=64')
        build_call.append('debug' if self.debug else 'release')
        if toolset == 'gcc':
            # There is no auto-link on MinGW. We don't want to determine the
            # exact compiler version when linking, so keep the naming simple.
            build_call.append('--layout=system')
        subprocess.check_call(build_call, cwd=build_dir)
