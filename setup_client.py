from distutils.ccompiler import get_default_compiler
from distutils.errors import DistutilsOptionError
from distutils.spawn import find_executable

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext as setuptools_build_ext

from time import sleep
import subprocess

import os
import sys

class build_client(setuptools_build_ext):
    setuptools_build_ext.user_options.append(('force-mingw', None,
        'force building with mingw'))
    setuptools_build_ext.boolean_options.append(('force-mingw'))

    def initialize_options(self):
        super().initialize_options()
        self.build_base = None
        self.force_mingw = False
        self.x64 =  sys.maxsize > 2**32

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'))
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()
        extra_compile_args = []
        extra_link_args = []
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
            ext_module.extra_link_args.extend(extra_link_args)

    __boost_libs = ['chrono', 'system', 'thread', 'date_time']

    def build_boost(self):
        build_boost = self.get_finalized_command('build_boost')
        build_boost.boost_libs.extend(self.__boost_libs)
        build_boost.x86 = True
        build_boost.x64 = True
        self.run_command('build_boost')
        self.include_dirs.append(os.path.abspath(build_boost.boost_build_dir))
        if self.x64:
            self.library_dirs.append(os.path.abspath(build_boost.library_dir_x64()))
        else:
            self.library_dirs.append(os.path.abspath(build_boost.library_dir_x86()))
        if self.compiler == 'mingw32':
            self.libraries.extend(build_boost.libraries)
        return build_boost

    def build_clang(self):
        build_clang = self.get_finalized_command('build_clang')
        build_clang.x86 = True
        build_clang.x64 = True
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
        return build_clang

    def build_client(self):
        build_boost = self.get_finalized_command('build_boost')
        build_clang = self.get_finalized_command('build_clang')
        boost_build_dir = build_boost.boost_build_dir
        b2 = find_executable('b2', boost_build_dir)
        assert b2 is not None

        # Build Client executable
        env = os.environ
        env['BOOST_BUILD_PATH'] = os.path.join(boost_build_dir, 'tools', 'build', 'v2')
        asm_inc_dir = os.path.abspath(os.path.join(self.build_temp, 'Loader'))
        from BuildDeps.generate_loader_asm import main as generate_loader_asm
        generate_loader_asm('Extensions/MapFiles/Loader/loader.cpp', asm_inc_dir, self.build_temp)
        call = [b2,
            'toolset={}'.format('msvc' if self.compiler == 'msvc' else 'gcc'),
            '-sBOOST_ROOT={}'.format(os.path.abspath(boost_build_dir)),
            '-sBOOST_LIBS={}'.format(" ".join(self.__boost_libs)),
            '-sCLANG_BUILD_ROOT_X86={}'.format(os.path.abspath(build_clang.get_build_dir_x86())),
            '-sCLANG_BUILD_ROOT_X64={}'.format(os.path.abspath(build_clang.get_build_dir_x64())),
            '-sCLANG_SRC_ROOT={}'.format(os.path.abspath(build_clang.clang_src_dir)),
            '-sTARGET_DIR={}'.format(os.getcwd()),
            '-sTMP_INCLUDE_DIR={}'.format(os.path.abspath(self.build_temp)),
            '-sBUILD_DIR={}'.format(os.path.join(os.path.abspath(self.build_base), 'client')),
        ]
        if sys.maxsize > 2**32:
            call.append('address-model=64')
        if self.force:
            call.append('-a')
        call.append('debug' if self.debug else 'release')
        subprocess.check_call(call, env=env, cwd='Executables\Client')

    def run(self):
        self.build_boost()
        self.build_clang()
        self.build_client()
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
        ),
        Extension('buildpal_client',
            sources = [
                'Extensions/Client/client.cpp',
                'Extensions/Client/pythonBindings.cpp',
            ],
            define_macros = [
                ('BOOST_ASIO_DISABLE_BOOST_REGEX', '1'),
                ('BOOST_ASIO_DISABLE_BOOST_DATE_TIME', '1')
            ],
            libraries = ['shlwapi'],
            #extra_compile_args = ['/Zi', '/Od'],
            #extra_link_args = ['/DEBUG'],
        ),
    ],
    cmdclass =  {'build_ext': build_client},
    command_packages = 'BuildDeps',
    package_dir = {'': 'Python'},
    packages = ['buildpal_manager', 'buildpal_common', 'buildpal_manager.compilers'],
    entry_points = {
        'console_scripts': ['buildpal_manager = buildpal_manager.__main__']
    }
)
