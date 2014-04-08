from .utils import get_from_github

from distutils.cmd import Command
import distutils.ccompiler

from multiprocessing import cpu_count

import os
import shutil
import subprocess
import sys
import zipfile

from io import BytesIO

class build_clang(Command):
    description = "build LLVM/Clang"

    user_options = [
        ('build-base='         , None, 'base directory for LLVM/Clang'),
        ('clang-src-dir='      , None, 'checkout directory for LLVM/Clang'),
        ('clang-build-dir='    , None, 'build directory for LLVM/Clang'),
        ('llvm-github-user='   , None, 'Github LLVM username'),
        ('llvm-github-repo='   , None, 'Github LLVM repository'),
        ('llvm-github-branch=' , None, 'Github LLVM branch'),
        ('clang-github-user='  , None, 'Github Clang username'),
        ('clang-github-repo='  , None, 'Github Clang repository'),
        ('clang-github-branch=', None, 'Github Clang branch'),
        ('compiler='           , None, 'Compiler'),
        ('debug'               , None, 'compile in debug mode')
    ]

    boolean_options = ['debug']

    __clang_libs = [
        # Order is important (MinGW linker).
        'LLVMCore',
        'LLVMOption',
        'clangLex',
        'clangBasic',
        'clangDriver',
        'LLVMMC',
        'LLVMSupport',
    ]

    def initialize_options(self):
        self.build_base = None
        self.compiler = None
        self.debug = None
        self.clang_src_dir = 'llvm_clang_src'
        self.clang_build_dir = 'llvm_clang_build'
        self.llvm_github_user = 'llvm-mirror'
        self.llvm_github_repo = 'llvm'
        self.llvm_github_branch = 'release_34'
        self.clang_github_user = 'jivancic'
        self.clang_github_repo = 'clang'
        self.clang_github_branch = 'release_34_juraj'

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'))
        self.set_undefined_options('build_ext',
            ('compiler', 'compiler'),
            ('debug', 'debug'))
        self.clang_src_dir = os.path.join(self.build_base, self.clang_src_dir)
        self.clang_build_dir = os.path.join(self.build_base, self.clang_build_dir)


    def run(self):
        llvm_info = dict(user=self.llvm_github_user, repo=self.llvm_github_repo, branch=self.llvm_github_branch)
        clang_info = dict(user=self.clang_github_user, repo=self.clang_github_repo, branch=self.clang_github_branch)
        self.run_command('build_cmake')
        cmake_command = self.get_finalized_command('build_cmake')
        self.run_command('build_ninja')
        ninja_command = self.get_finalized_command('build_ninja')

        assert self.compiler is not None
        self.clang_build_dir += '_' + self.compiler

        self.win64 = sys.maxsize > 2**32
        if self.win64:
            self.clang_build_dir += '_x64'

        if self.debug:
            self.clang_build_dir += '_d'

        self.__build_clang(cmake_command.cmake_exe,
            os.path.abspath(ninja_command.ninja_exe), llvm_info, clang_info,
            self.clang_src_dir, self.clang_build_dir, self.build_base)
        build_ext = self.get_finalized_command('build_ext')
        build_ext.include_dirs.extend([
            os.path.join(self.clang_build_dir, 'include'),
            os.path.join(self.clang_build_dir, 'tools', 'clang', 'include'),
            os.path.join(self.clang_src_dir, 'include'),
            os.path.join(self.clang_src_dir, 'tools', 'clang', 'include')])
        build_ext.library_dirs.append(os.path.join(self.clang_build_dir, 'lib'))
        build_ext.libraries.extend(self.__clang_libs)
        if self.compiler == 'mingw32':
            build_ext.libraries.append('imagehlp')

    def __build_clang(self, cmake_exe, ninja_exe, llvm_info, clang_info,
            clang_src_dir, clang_build_dir, cache_dir):
        if self.compiler == 'msvc':
            distutils.msvc9compiler.VERSION = 11.0
            compiler = distutils.ccompiler.new_compiler(compiler='msvc')
            compiler.initialize('win-amd64' if self.win64 else 'win32')
            compiler_exe = compiler.cc
            compiler_cxx_exe = compiler.cc
        if self.compiler == 'mingw32':
            compiler = distutils.ccompiler.new_compiler(compiler='mingw32')
            compiler_exe = 'gcc'
            compiler_cxx_exe = 'g++'
        build_clang.__get_if_needed(llvm_info, clang_src_dir, cache_dir)
        build_clang.__get_if_needed(clang_info, os.path.join(clang_src_dir, 'tools/clang'), cache_dir)

        if not os.path.exists(os.path.join(clang_build_dir, 'build.ninja')):
            os.makedirs(clang_build_dir, exist_ok=True)
            subprocess.check_call([cmake_exe,
            '-DCMAKE_MAKE_PROGRAM:PATH={}'.format(ninja_exe),
            '-DCMAKE_C_COMPILER:PATH={}'.format(compiler_exe),
            '-DCMAKE_CXX_COMPILER:PATH={}'.format(compiler_cxx_exe),
            '-DPYTHON_EXECUTABLE:PATH={}'.format(sys.executable),
            '-DCMAKE_BUILD_TYPE={}'.format('Debug' if self.debug else 'Release'),
            '-GNinja', os.path.abspath(clang_src_dir)],
            cwd=clang_build_dir, env=os.environ)

        subprocess.check_call([ninja_exe, '-j{}'.format(cpu_count())] + build_clang.__clang_libs, cwd=clang_build_dir)

    @staticmethod
    def __get_if_needed(project_info, target_dir, cache_dir):
        if os.path.isdir(target_dir):
            print("Found '{}', assuming it contains {}:{}".format(target_dir, project_info['repo'], project_info['branch']))
            return
        get_from_github(project_info, target_dir, cache_dir)
