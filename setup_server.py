import distutils.ccompiler
from distutils.command.build_clib import build_clib
from distutils.ccompiler import get_default_compiler, new_compiler
from distutils.spawn import find_executable
from setuptools import setup, Extension

from setuptools.command.build_ext import build_ext as setuptools_build_ext

import sys
import os

class build_inject_dll(build_clib):
    def initialize_options(self):
        super().initialize_options()
        self.compile_args = []
        self.link_libs = []
        self.plat = None

    def finalize_options(self):
        self.set_undefined_options('build',
                            ('build_lib', 'build_clib'))
        return super().finalize_options()

    def run(self):
        assert self.libraries
        self.build_libraries(self.libraries)

    def prepare_compiler(self, plat):
        compiler = new_compiler(compiler=self.compiler,
            dry_run=self.dry_run,
            force=self.force)
        compiler.initialize(plat)

        if self.include_dirs is not None:
            compiler.set_include_dirs(self.include_dirs)
        if self.define is not None:
            # 'define' option is a list of (name,value) tuples
            for (name,value) in self.define:
                compiler.define_macro(name, value)
        if self.undef is not None:
            for macro in self.undef:
                compiler.undefine_macro(macro)
        return compiler

    def build_libraries(self, libraries):
        for (lib_name, build_info) in libraries:
            compiler = self.prepare_compiler(build_info.get('plat'))
            sources = build_info.get('sources')
            if sources is None or not isinstance(sources, (list, tuple)):
                raise DistutilsSetupError(
                       "in 'libraries' option (library '%s'), "
                       "'sources' must be present and must be "
                       "a list of source filenames" % lib_name)
            sources = list(sources)

            macros = build_info.get('macros')
            include_dirs = build_info.get('include_dirs')
            objects = compiler.compile(sources,
                output_dir=self.build_temp,
                macros=macros,
                include_dirs=include_dirs,
                debug=self.debug,
                extra_preargs=self.compile_args)

            compiler.link_shared_lib(objects, lib_name,
                output_dir=self.build_clib,
                debug=self.debug,
                libraries=self.link_libs,
                extra_preargs=[
                    '/DEF:{}'.format(build_info['def_file']),
                ])

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

        build_inject_dll = self.get_finalized_command('build_inject_dll')
        asm_inc_dir = os.path.abspath(os.path.join(self.build_temp, 'Loader'))
        from BuildDeps.generate_loader_asm import main as generate_loader_asm
        generate_loader_asm('Extensions/MapFiles/Loader/loader.cpp', asm_inc_dir, self.build_temp)
        build_inject_dll.libraries = [
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
        build_inject_dll.compile_args.append('/EHsc')
        build_inject_dll.link_libs.append('shlwapi')
        build_inject_dll.link_libs.append('psapi')
        build_inject_dll.link_libs.append('user32')
        self.run_command('build_inject_dll')

        self.library_dirs.append(build_inject_dll.build_clib)
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
            ]
        ),
    ],
    cmdclass =  {'build_ext': build_ext,
        'build_inject_dll': build_inject_dll
    },
    command_packages = 'BuildDeps',
    package_dir = {'': 'Python'},
    packages = ['buildpal_server', 'buildpal_common'],
    entry_points = {
        'console_scripts': ['buildpal_server = buildpal_server.__main__']
    }
)
