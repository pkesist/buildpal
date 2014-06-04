from setuptools import setup, Extension

from BuildDeps.build_ext import build_ext as _build_ext

import sys
import os

class build_ext(_build_ext):
    def run(self):
        self.setup_compiler()
        build_dll = self.get_finalized_command('build_dll')
        asm_inc_dir = os.path.abspath(os.path.join(self.build_temp, 'Loader'))
        from BuildDeps.generate_loader_asm import main as generate_loader_asm
        generate_loader_asm('Extensions/MapFiles/Loader/loader.cpp', asm_inc_dir, self.build_temp)
        build_dll.libraries = [
            ('map_files_inj32', dict(
                    sources=['Extensions/MapFiles/dllInject.cpp',
                        'Extensions/MapFiles/mapFiles.cpp'],
                    def_file='Extensions/MapFiles/mapFiles.def',
                    include_dirs=[os.path.dirname(asm_inc_dir)],
                    plat='win32'
                )
            ),
            ('map_files_inj64', dict(
                    sources=['Extensions/MapFiles/dllInject.cpp',
                        'Extensions/MapFiles/mapFiles.cpp'],
                    def_file='Extensions/MapFiles/mapFiles.def',
                    include_dirs=[os.path.dirname(asm_inc_dir)],
                    plat='win-amd64'
                )
            )
        ]
        build_dll.compile_args.extend(self.extra_compile_args)
        build_dll.link_args.extend(self.extra_link_args)
        build_dll.link_libs.append('psapi')
        build_dll.link_libs.append('user32')
        build_dll.link_libs.append('shlwapi')
        self.run_command('build_dll')
        self.additional_package_data = [('', ['map_files_inj32.dll', 'map_files_inj64.dll'])]

        self.library_dirs.append(build_dll.build_clib)
        win64 = sys.maxsize > 2**32
        self.libraries.append('map_files_inj64' if win64 else 'map_files_inj32')
        super().run()

setup(name = 'buildpal_server',
    version = '0.1',
    description = 'BuildPal Server package',
    ext_modules = [
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
    packages = ['buildpal_server', 'buildpal_common'],
    entry_points = {
        'console_scripts': ['buildpal_server = buildpal_server.__main__']
    }
)
