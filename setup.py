from distutils.core import setup, Extension
from distutils.command.build import build as distutils_build
from distutils.ccompiler import get_default_compiler

class custom_build(distutils_build):
    def finalize_options(self):
        super().finalize_options()
        if self.compiler is None:
            self.compiler = get_default_compiler()
        extra_compile_args = []
        if self.compiler == 'msvc':
            extra_compile_args.append('/EHsc')
        elif self.compiler == 'mingw32':
            extra_compile_args.append('-std=c++11')
        else:
            raise Exception('Unsupported compiler')
        for ext_module in self.distribution.ext_modules:
            ext_module.extra_compile_args.extend(extra_compile_args)

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
    ]
)

parse_args = Extension('parse_args',
    sources = [
        'Extensions/ArgParser/argList_.cpp',
        'Extensions/ArgParser/clangOpts_.cpp',
    ]
)

setup(name = 'BuildPal Client',
    version = '0.1',
    description = 'BuildPal Client package',
    ext_modules = [preprocessing, parse_args],
    cmdclass =  {'build': custom_build},
    command_packages = 'BuildDeps',
)
