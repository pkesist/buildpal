from distutils.cmd import Command
from distutils.core import setup, Extension
from distutils.ccompiler import get_default_compiler
from distutils.errors import DistutilsOptionError
from distutils.spawn import find_executable
from distutils.command.build import build as distutils_build

import os
import subprocess
import sys

class build_client(distutils_build):
    def initialize_options(self):
        super().initialize_options()

    def finalize_options(self):
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()

    __boost_libs = ['chrono', 'system', 'thread', 'date_time']

    def run(self):
        build_boost = self.get_finalized_command('build_boost')
        build_boost.boost_libs.extend(self.__boost_libs)
        build_boost.x86 = True
        build_boost.x64 = True
        self.run_command('build_boost')

        build_clang = self.get_finalized_command('build_clang')
        build_clang.x86 = True
        build_clang.x64 = True
        self.run_command('build_clang')

        if self.compiler == 'mingw32':
            pass
        elif self.compiler == 'msvc':
            pass
        else:
            raise DistutilsOptionError("Unsupported compiler '{}'.".format(self.compiler))
        build_boost = self.get_finalized_command('build_boost')
        build_clang = self.get_finalized_command('build_clang')
        boost_build_dir = build_boost.boost_build_dir
        b2 = find_executable('b2', boost_build_dir)
        assert b2 is not None
        clang_src_dir = build_clang.clang_src_dir
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
            '-sCLANG_SRC_ROOT={}'.format(os.path.abspath(clang_src_dir)),
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

setup(name = 'buildpal_client',
    version = '0.1',
    description = 'BuildPal Client executable',
    cmdclass = {
        'build': build_client
    },
    command_packages = 'BuildDeps',
)
