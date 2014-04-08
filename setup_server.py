import distutils.ccompiler
from distutils.ccompiler import get_default_compiler
from distutils.command.build_ext import build_ext as distutils_build_ext
from distutils.spawn import find_executable
from setuptools import setup, Extension
import subprocess
import sys
import os

class build_ext(distutils_build_ext):
    def initialize_options(self):
        super().initialize_options()

    def finalize_options(self):
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()

    def run(self):
        # For Boost.Build system.
        self.run_command('build_boost')
        extra_compile_args = []
        extra_link_args = []
        win64 = sys.maxsize > 2**32
        if self.compiler == 'mingw32':
            extra_compile_args.append('-std=c++11')
        elif self.compiler == 'msvc':
            distutils.msvc9compiler.VERSION = 11.0
            extra_compile_args.append('/EHsc')
        else:
            raise DistutilsOptionError("Unsupported compiler '{}'.".format(self.compiler))

        build_boost = self.get_finalized_command('build_boost')
        boost_build_dir = build_boost.boost_build_dir
        b2 = find_executable('b2', boost_build_dir)
        assert b2 is not None

        env = os.environ
        env['BOOST_BUILD_PATH'] = os.path.abspath(os.path.join(boost_build_dir, 'tools', 'build', 'v2'))
        call = [b2,
            'toolset={}'.format('msvc' if self.compiler == 'msvc' else 'gcc'),
            '-sTARGET_DIR={}'.format(os.path.abspath(self.build_lib)),
            '--build-dir={}'.format(os.path.join(os.path.abspath(self.build_temp), 'client'))
        ]
        if win64:
            call.append('address-model=64')
        if self.force:
            call.append('-a')

        subprocess.check_call(call, env=env, cwd='Extensions\MapFiles')
        self.library_dirs.append(self.build_lib)
        self.libraries.append('map_files_inj64' if win64 else 'map_files_inj32')
        for ext_module in self.distribution.ext_modules:
            ext_module.extra_compile_args.extend(extra_compile_args)
            ext_module.extra_link_args.extend(extra_link_args)
        super().run()

setup(name = 'buildpal_server',
    version = '0.1',
    description = 'BuildPal Server package',
    ext_modules = [
        Extension('map_files',
            sources = [
                'Extensions/MapFiles/pydll.cpp',
            ]
        ),
    ],
    cmdclass =  {'build_ext': build_ext},
    command_packages = 'BuildDeps',
    package_dir = {
        'buildpal_server': 'Python/buildpal_server',
        'buildpal_common': 'Python/buildpal_common'
    },
    packages = ['buildpal_server', 'buildpal_common'],
    entry_points = {
        'console_scripts': ['buildpal_server = buildpal_server.__main__']
    }
)
