from distutils.errors import DistutilsOptionError
from distutils.spawn import find_executable

from setuptools import Extension, setup
from BuildDeps.build_ext import build_ext as _build_ext

from time import sleep
import subprocess

import os
import sys

class build_ext(_build_ext):
    _build_ext.user_options.append(('force-mingw', None,
        'force building with mingw'))
    _build_ext.boolean_options.append(('force-mingw'))

    def initialize_options(self):
        super().initialize_options()
        self.build_base = None
        self.build_lib = None
        self.force_mingw = False
        self.x64 =  sys.maxsize > 2 ** 32

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'))
        super().finalize_options()

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

    def generate_loader(self):
        self.asm_inc_dir = os.path.abspath(os.path.join(self.build_temp, 'Loader'))
        os.makedirs(self.asm_inc_dir, exist_ok=True)
        from BuildDeps.generate_loader_asm import generate_code
        generate_code('win32', 'Extensions/Common/Loader/loader.cpp',
            os.path.join(self.asm_inc_dir, 'loader32.inc'), self.build_temp)
        generate_code('win-amd64', 'Extensions/Common/Loader/loader.cpp',
            os.path.join(self.asm_inc_dir, 'loader64.inc'), self.build_temp)

    def build_client(self):
        build_boost = self.get_finalized_command('build_boost')
        build_clang = self.get_finalized_command('build_clang')
        boost_build_dir = build_boost.boost_build_dir
        b2 = find_executable('b2', boost_build_dir)
        assert b2 is not None

        # Build Client executable
        call = [b2,
            'toolset={}'.format('msvc' if self.compiler == 'msvc' else 'gcc'),
            '-sBOOST_BUILD_PATH="{}"'.format(os.path.abspath(os.path.join(boost_build_dir, 'tools', 'build', 'v2'))),
            '-sBOOST_PATH="{}"'.format(os.path.abspath(boost_build_dir)),
            '-sBOOST_LIBS={}'.format(" ".join(self.__boost_libs)),
            '-sCLANG_BUILD_ROOT_X86="{}"'.format(os.path.abspath(build_clang.get_build_dir_x86())),
            '-sCLANG_BUILD_ROOT_X64="{}"'.format(os.path.abspath(build_clang.get_build_dir_x64())),
            '-sCLANG_SRC_ROOT="{}"'.format(os.path.abspath(build_clang.clang_src_dir)),
            '-sTARGET_DIR="{}"'.format(os.path.abspath(self.build_lib)),
            '-sTMP_INCLUDE_DIR="{}"'.format(os.path.abspath(self.build_temp)),
            '-sBUILD_DIR="{}"'.format(os.path.join(os.path.abspath(self.build_base), 'client')),
        ]
        if sys.maxsize > 2 ** 32:
            call.append('address-model=64')
        if self.force:
            call.append('-a')
        if self._debug:
            call.append('debug-symbols=on')
            call.append('optimization=off')
        call.append('release')
        subprocess.check_call(call, cwd='Executables/Client')
        self.additional_package_data.append(('', ('bp_cli_inj32.dll',
            'bp_cli_inj64.dll', 'bp_cl.exe')))

        win64 = sys.maxsize > 2**32
        self.library_dirs.append(self.build_lib)
        self.libraries.append('bp_cli_inj64' if win64 else 'bp_cli_inj32')


    def build_server(self):
        build_dll = self.get_finalized_command('build_dll')
        build_dll.libraries = [
            ('map_files_inj32', dict(
                sources=['Extensions/Common/dllInject.cpp',
                    'Extensions/MapFiles/mapFiles.cpp'],
                def_file='Extensions/MapFiles/mapFiles.def',
                include_dirs=[os.path.dirname(self.asm_inc_dir)],
                plat='win32')
            ),
            ('map_files_inj64', dict(
                sources=['Extensions/Common/dllInject.cpp',
                    'Extensions/MapFiles/mapFiles.cpp'],
                def_file='Extensions/MapFiles/mapFiles.def',
                include_dirs=[os.path.dirname(self.asm_inc_dir)],
                plat='win-amd64')
            )
        ]
        build_dll.compile_args.extend(self.extra_compile_args)
        build_dll.link_args.extend(self.extra_link_args)
        build_dll.link_libs.append('psapi')
        build_dll.link_libs.append('user32')
        build_dll.link_libs.append('shlwapi')
        self.run_command('build_dll')
        self.additional_package_data.append(('', ['map_files_inj32.dll', 'map_files_inj64.dll']))

        self.library_dirs.append(build_dll.build_clib)
        win64 = sys.maxsize > 2**32
        self.libraries.append('map_files_inj64' if win64 else 'map_files_inj32')

    def run(self):
        self.setup_compiler()
        if self.compiler == 'mingw32':
            if not self.force_mingw:
                print("WARNING: Even though it is possible to build these \n"
                      "extensions with MinGW, the resulting DLL will crash \n"
                      "on load. If you *really* want to build it, add \n"
                      "--force-mingw option to build command")
                raise DistutilsOptionError("Unsupported compiler: Builds, but crashes.")
            for ext_module in self.distribution.ext_modules:
                ext_module.extra_compile_args.append('-std=c++11')

        self.build_boost()
        self.build_clang()
        self.generate_loader()
        self.build_client()
        self.build_server()
        super().run()

setup(name = 'buildpal',
    version = '0.1',
    description = 'BuildPal package',
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
                'Extensions/Common/createProcess.cpp'
            ],
            define_macros = [
                ('BOOST_ASIO_DISABLE_BOOST_REGEX', '1'),
                ('BOOST_ASIO_DISABLE_BOOST_DATE_TIME', '1')
            ],
            libraries = ['shlwapi'],
        ),
        Extension('map_files',
            sources = [
                'Extensions/MapFiles/pydll.cpp',
                'Extensions/Common/createProcess.cpp'
            ]
        ),
    ],
    cmdclass =  {'build_ext': build_ext},
    command_packages = 'BuildDeps',
    package_dir = {'': 'Python'},
    packages = [
        'buildpal',
        'buildpal.common',       
        'buildpal.server',
        'buildpal.manager'],
    entry_points = {
        'console_scripts': ['buildpal = __main__']
    }
)
