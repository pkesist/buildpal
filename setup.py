from distutils.core import setup, Extension
from distutils.command.build import build as distutils_build
from distutils.ccompiler import get_default_compiler
from distutils.errors import DistutilsOptionError

from time import sleep

class custom_build(distutils_build):
    distutils_build.user_options.append(('force-mingw', None,
        'force building with mingw'))
    distutils_build.boolean_options.append(('force-mingw'))

    def initialize_options(self):
        super().initialize_options()
        self.force_mingw = False

    def finalize_options(self):
        super().finalize_options()
        if self.compiler is None:
            self.compiler = get_default_compiler()
        extra_compile_args = []
        if self.compiler == 'msvc':
            extra_compile_args.append('/EHsc')
        elif self.compiler == 'mingw32':
            if not self.force_mingw:
                print("WARNING: Even though it is possible to build these \n"
                      "extensions with MinGW, the resulting DLL will crash \n"
                      "on load. If you really want to build it add \n"
                      "--force-mingw option to build command")
                sleep(2)
                raise DistutilsOptionError("Mingw does not work")
            extra_compile_args.append('-std=c++11')
        else:
            raise Exception('Unsupported compiler')
        self.build_temp += '_' + self.compiler
        #self.build_lib += '_' + self.compiler
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

setup(name = 'buildpal_mgr',
    version = '0.1',
    description = 'BuildPal Manager package',
    ext_modules = [preprocessing, parse_args],
    cmdclass =  {'build': custom_build},
    command_packages = 'BuildDeps',
)
