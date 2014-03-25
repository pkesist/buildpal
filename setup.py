from distutils.core import setup, Extension
from distutils.command.build import build as distutils_build

class custom_build(distutils_build):
    def run(self):
        self.run_command('build_boost')
        self.run_command('build_clang')
        distutils_build.run(self)

preprocessing = Extension('preprocessing',
    sources = [
        'Extensions/HeaderScanner/contentCache_.cpp',
        'Extensions/HeaderScanner/headerCache_.cpp',
        'Extensions/HeaderScanner/headerScanner_.cpp',
        'Extensions/HeaderScanner/headerTracker_.cpp',
        'Extensions/HeaderScanner/pythonBindings_.cpp',
        'Extensions/HeaderScanner/utility_.cpp',
    ],
    extra_compile_args = ['/EHsc'],
)

parse_args = Extension('parse_args',
    sources = [
        'Extensions/ArgParser/argList_.cpp',
        'Extensions/ArgParser/clangOpts_.cpp',
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
