from distutils.cmd import Command
from distutils.core import setup, Extension
from distutils.ccompiler import get_default_compiler
from distutils.errors import DistutilsOptionError
from distutils.spawn import find_executable
from distutils.command.build import build as distutils_build

import os
import subprocess

class build_client(distutils_build):
    def initialize_options(self):
        super().initialize_options()

    def finalize_options(self):
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()

    __boost_libs = ['chrono', 'filesystem', 'system', 'timer']

    def run(self):
        build_boost = self.get_finalized_command('build_boost')
        build_boost.boost_libs.extend(self.__boost_libs)
        self.run_command('build_boost')
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
        clang_build_dir = build_clang.clang_build_dir
        env = os.environ
        env['BOOST_BUILD_PATH'] = os.path.join(boost_build_dir, 'tools', 'build', 'v2')
        call = [b2,
            'toolset={}'.format('msvc' if self.compiler == 'msvc' else 'gcc'),
            '-sBOOST_ROOT={}'.format(os.path.abspath(boost_build_dir)),
            '-sBOOST_LIBS={}'.format(" ".join(self.__boost_libs)),
            '-sCLANG_BUILD_ROOT={}'.format(os.path.abspath(clang_build_dir)),
            '-sCLANG_SRC_ROOT={}'.format(os.path.abspath(clang_src_dir)),
            '-sTARGET_DIR={}'.format(os.getcwd()),
            '--build-dir={}'.format(os.path.join(os.path.abspath(self.build_base), 'client'))
        ]
        if self.force:
            call.append('-a')
        subprocess.check_call(call, env=env, cwd='Executables\Client')

setup(name = 'buildpal_client',
    version = '0.1',
    description = 'BuildPal Client executable',
    cmdclass = {
        'build': build_client
    },
    command_packages = 'BuildDeps',
)
