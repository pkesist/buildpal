import distutils.ccompiler
from distutils.ccompiler import get_default_compiler
from distutils.file_util import copy_file
from setuptools.command.build_ext import build_ext as _build_ext

import os

class build_ext(_build_ext):
    def initialize_options(self):
        super().initialize_options()
        self.additional_package_data = None

    def finalize_options(self):
        super().finalize_options()
        self.set_undefined_options('build',
            ('debug', 'debug'))
        self._debug = self.debug
        # We never want to build real debug extensions as they require
        # debug python.
        self.debug = False
        self.additional_package_data = self.additional_package_data or []

    def setup_compiler(self):
        self.compiler = self.compiler or get_default_compiler()
        self.extra_compile_args = []
        self.extra_link_args = []
        if self.compiler == 'msvc':
            distutils.msvc9compiler.VERSION = 11.0
            self.extra_compile_args.append('/EHsc')
            if self._debug:
                self.extra_compile_args.extend(['/Zi', '/Od'])
                self.extra_link_args.extend(['/DEBUG'])
            else:
                self.extra_compile_args.extend(['/GF', '/GL', '/GT', '/Gy'])
                self.extra_link_args.extend(['/OPT:REF', '/OPT:ICF', '/LTCG'])

        for ext_module in self.distribution.ext_modules:
            ext_module.extra_compile_args.extend(self.extra_compile_args)
            ext_module.extra_link_args.extend(self.extra_link_args)

    def copy_extensions_to_source(self):
        """ Needed to make develop target work """
        super().copy_extensions_to_source()
        build_py = self.get_finalized_command('build_py')
        for package, filelist in self.additional_package_data:
            package_dir = build_py.get_package_dir(package)
            for filename in filelist:
                dest_filename = os.path.join(package_dir, filename)
                src_filename = os.path.join(self.build_lib,filename)

                copy_file(
                    src_filename, dest_filename, verbose=self.verbose,
                    dry_run=self.dry_run
                )
