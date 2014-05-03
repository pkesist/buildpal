from distutils.ccompiler import get_default_compiler
from distutils.errors import DistutilsOptionError

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext as setuptools_build_ext

from time import sleep

import os
import sys

class build_ext(setuptools_build_ext):
    setuptools_build_ext.user_options.append(('force-mingw', None,
        'force building with mingw'))
    setuptools_build_ext.boolean_options.append(('force-mingw'))

    def initialize_options(self):
        super().initialize_options()
        self.force_mingw = False
        self.x64 =  sys.maxsize > 2**32

    def finalize_options(self):
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()
        extra_compile_args = []
        if self.compiler == 'msvc':
            extra_compile_args.append('/EHsc')
        elif self.compiler == 'mingw32':
            if not self.force_mingw:
                print("WARNING: Even though it is possible to build these \n"
                      "extensions with MinGW, the resulting DLL will crash \n"
                      "on load. If you *really* want to build it, add \n"
                      "--force-mingw option to build command")
                raise DistutilsOptionError("Unsupported compiler: Builds, but crashes.")
            extra_compile_args.append('-std=c++11')
        else:
            raise DistutilsOptionError('Unsupported compiler')
        for ext_module in self.distribution.ext_modules:
            ext_module.extra_compile_args.extend(extra_compile_args)

    def run(self):
        build_boost = self.get_finalized_command('build_boost')
        build_boost.boost_libs.append('chrono')
        build_boost.boost_libs.append('date_time')
        build_boost.boost_libs.append('system')
        build_boost.boost_libs.append('thread')
        self.run_command('build_boost')
        self.include_dirs.append(os.path.abspath(build_boost.boost_build_dir))
        if self.x64:
            self.library_dirs.append(os.path.abspath(build_boost.library_dir_x64()))
        else:
            self.library_dirs.append(os.path.abspath(build_boost.library_dir_x86()))
        if self.compiler == 'mingw32':
            self.libraries.extend(build_boost.libraries)

        build_clang = self.get_finalized_command('build_clang')
        self.run_command('build_clang')
        if self.x64:
            build_dir = build_clang.get_build_dir_x64()
        else:
            build_dir = build_clang.get_build_dir_x86()
        self.include_dirs.extend([
            os.path.join(build_dir, 'include'),
            os.path.join(build_dir, 'tools', 'clang', 'include'),
            os.path.join(build_clang.clang_src_dir, 'include'),
            os.path.join(build_clang.clang_src_dir, 'tools', 'clang', 'include')])
        self.library_dirs.append(os.path.join(build_dir, 'lib'))
        self.libraries.extend(build_clang.get_libs())
        if self.compiler == 'mingw32':
            self.libraries.append('imagehlp')
        super().run()


setup(name = 'buildpal_manager',
    version = '0.1',
    description = 'BuildPal Manager package',
    ext_modules = [
        Extension('preprocessing',
            sources = [
                'Extensions/HeaderScanner/contentCache_.cpp',
                'Extensions/HeaderScanner/headerCache_.cpp',
                'Extensions/HeaderScanner/headerScanner_.cpp',
                'Extensions/HeaderScanner/headerTracker_.cpp',
                'Extensions/HeaderScanner/pythonBindings_.cpp',
                'Extensions/HeaderScanner/utility_.cpp',
            ]
        ),
        Extension('parse_args',
            sources = [
                'Extensions/ArgParser/argList_.cpp',
                'Extensions/ArgParser/clangOpts_.cpp',
            ]
        )
    ],
    cmdclass =  {'build_ext': build_ext},
    command_packages = 'BuildDeps',
    package_dir = {'': 'Python'},
    packages = ['buildpal_manager', 'buildpal_common', 'buildpal_manager.compilers'],
    entry_points = {
        'console_scripts': ['buildpal_manager = buildpal_manager.__main__']
    }
)
