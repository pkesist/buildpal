import distutils.ccompiler
from distutils.ccompiler import get_default_compiler
from setuptools import setup, Extension

from setuptools.command.build_ext import build_ext as setuptools_build_ext

import sys
import os

class build_ext(setuptools_build_ext):
    def initialize_options(self):
        super().initialize_options()

    def finalize_options(self):
        super().finalize_options()
        self.compiler = self.compiler or get_default_compiler()

    def run(self):
        if self.compiler == 'msvc':
            distutils.msvc9compiler.VERSION = 11.0
            pass
        else:
            raise DistutilsOptionError("Unsupported compiler '{}'.".format(self.compiler))

        build_dll = self.get_finalized_command('build_dll')
        asm_inc_dir = os.path.abspath(os.path.join(self.build_temp, 'Loader'))
        from BuildDeps.generate_loader_asm import main as generate_loader_asm
        generate_loader_asm('Extensions/MapFiles/Loader/loader.cpp', asm_inc_dir, self.build_temp)
        build_dll.libraries = [
            ('map_files_inj32', dict(
                    sources=['Extensions/MapFiles/dllInject.cpp',
                        'Extensions/MapFiles/mapFilesInject.cpp'],
                    def_file='Extensions/MapFiles/mapFilesInject.def',
                    include_dirs=[os.path.dirname(asm_inc_dir)],
                    plat='win32'
                )
            ),
            ('map_files_inj64', dict(
                    sources=['Extensions/MapFiles/dllInject.cpp',
                        'Extensions/MapFiles/mapFilesInject.cpp'],
                    def_file='Extensions/MapFiles/mapFilesInject.def',
                    include_dirs=[os.path.dirname(asm_inc_dir)],
                    plat='win-amd64'
                )
            )
        ]
        build_dll.compile_args.append('/EHsc')
        #build_dll.compile_args.append('/Od')
        #build_dll.compile_args.append('/Zi')
        #build_dll.link_args.append('/DEBUG')
        build_dll.link_libs.append('psapi')
        build_dll.link_libs.append('user32')
        build_dll.link_libs.append('shlwapi')
        self.run_command('build_dll')

        self.library_dirs.append(build_dll.build_clib)
        win64 = sys.maxsize > 2**32
        self.libraries.append('map_files_inj64' if win64 else 'map_files_inj32')
        for ext_module in self.distribution.ext_modules:
            #ext_module.extra_compile_args.extend(['/EHsc', '/Od', '/Zi'])
            ext_module.extra_compile_args.extend(['/EHsc'])
            ext_module.extra_link_args.extend(['/DEBUG'])
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
    package_dir = {'': 'Python'},
    packages = ['buildpal_server', 'buildpal_common'],
    entry_points = {
        'console_scripts': ['buildpal_server = buildpal_server.__main__']
    }
)
