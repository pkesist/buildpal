import os
from setuptools.command.build_ext import build_ext as _build_ext
from distutils.file_util import copy_file

class build_ext(_build_ext):
    def initialize_options(self):
        super().initialize_options()
        self.additional_package_data = None

    def finalize_options(self):
        super().finalize_options()
        self.additional_package_data = self.additional_package_data or []

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
