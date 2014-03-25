from .utils import get_zip

from distutils.cmd import Command
from distutils.spawn import find_executable

import os

class build_cmake(Command):
    description = "build CMake build system"

    user_options = [
        ('cmake-version=', None, 'CMake version to use'),
        ('build-base=', None, 'base directory for Cmake build'),
        ('cmake-dir=', None, 'directory where to build CMake')
    ]

    def initialize_options(self):
        self.cmake_version = None
        self.build_base = None
        self.cmake_dir = None

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'))

        if self.cmake_version is None:
            self.cmake_version = (2, 8, 12, 2)
        else:
            self.cmake_version = tuple(int(x) for x in
                self.boost_version.split('.'))

        if self.cmake_dir is None:
            self.cmake_dir = 'cmake_{}_{}_{}_{}'.format(*self.cmake_version)

    def run(self):
        final_build_dir = os.path.join(self.build_base, self.cmake_dir)
        self.cmake_exe = find_executable('cmake', os.path.join(final_build_dir, 'bin'))
        if self.cmake_exe is None:
            self.__build_cmake(self.cmake_version, final_build_dir, self.build_base)
            self.cmake_exe = find_executable('cmake', os.path.join(final_build_dir, 'bin'))
            assert self.cmake_exe

    @staticmethod
    def __build_cmake(cmake_version, build_dir, cache_dir):
        # On Windows we need CMake to build CMake.
        # In other words, if you build CMake on Windows, you are either CMake
        # developer pushing a new release, or you are an idiot :(
        url = "http://www.cmake.org/files/v{0}.{1}/cmake-{0}.{1}.{2}.{3}-win32-x86.zip".format(*cmake_version)

        if not os.path.isdir(build_dir):
            get_zip(url, build_dir, cache_dir)
        else:
            print("Found '{}', assuming it contains Cmake {}.{}.{}.{}".format(build_dir, *cmake_version))
