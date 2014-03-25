from distutils.core import setup, Extension
from distutils.command.build import build as distutils_build

class custom_build(distutils_build):
    def run(self):
        distutils_build.run(self)

    sub_commands = [('build_boost', None), ('build_clang', None)] \
        + distutils_build.sub_commands

preprocessing = Extension('preprocessing',
    sources = [
        'Source/HeaderScanner/contentCache_.cpp',
        'Source/HeaderScanner/headerCache_.cpp',
        'Source/HeaderScanner/headerScanner_.cpp',
        'Source/HeaderScanner/headerTracker_.cpp',
        'Source/HeaderScanner/pythonBindings_.cpp',
        'Source/HeaderScanner/utility_.cpp',
    ],
    extra_compile_args = ['/EHsc'],
)

parse_args = Extension('parse_args',
    sources = [
        'Source/ArgParser/argList_.cpp',
        'Source/ArgParser/clangOpts_.cpp',
    ],
    extra_compile_args = ['/EHsc'],
)

setup(name = 'BuildPal Client',
    version = '0.1',
    description = 'BuildPal Client package',
    ext_modules = [preprocessing, parse_args],
    cmdclass =  {'build': custom_build},
    command_packages = 'BuildDeps',
)
