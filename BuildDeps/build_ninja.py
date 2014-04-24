from .utils import get_from_github
import distutils.ccompiler

import subprocess
from distutils.cmd import Command
from distutils.spawn import find_executable
import sys

import os

class build_ninja(Command):
    description = "build Ninja build system"

    user_options = [
        ('build-base='         , None, 'base directory for LLVM/Clang'),
        ('ninja-build-dir='    , None, 'build directory for Ninja'),
        ('ninja-github-user='  , None, 'Github Ninja username'),
        ('ninja-github-repo='  , None, 'Github Ninja repository'),
        ('ninja-github-branch=', None, 'Github Ninja branch'),
        ('compiler='           , None, 'Compiler'),
    ]

    def initialize_options(self):
        self.build_base = None
        self.compiler = None
        self.ninja_build_dir = 'ninja'
        self.ninja_github_user = 'martine'
        self.ninja_github_repo = 'ninja'
        self.ninja_github_branch = 'release'

    def finalize_options(self):
        self.set_undefined_options('build',
            ('build_base', 'build_base'),
            ('compiler', 'compiler'),)

    def run(self):
        if self.compiler is None:
            self.compiler = distutils.ccompiler.get_default_compiler()
        bootstrap_args = []
        win64 = sys.maxsize > 2**32
        if self.compiler == 'msvc':
            bootstrap_args = ['--platform=msvc']
            distutils.msvc9compiler.VERSION = 11.0
            compiler = distutils.ccompiler.new_compiler(compiler='msvc')
            compiler.initialize('win-amd64' if win64 else 'win32')
        elif self.compiler == 'mingw32':
            bootstrap_args = ['--platform=mingw']

        ninja_info = dict(user=self.ninja_github_user,
            repo=self.ninja_github_repo, branch=self.ninja_github_branch)
        self.ninja_build_dir += '_' + self.compiler
        final_dir = os.path.join(self.build_base, self.ninja_build_dir)
        if os.path.isdir(final_dir):
            print("Found '{}', assuming it contains {}:{}".format(
                final_dir, ninja_info['repo'], ninja_info['branch']))
        else:
            get_from_github(ninja_info, final_dir, self.build_base)
        self.ninja_exe = find_executable('ninja', final_dir)
        if self.ninja_exe is None:
            subprocess.check_call([sys.executable, 'bootstrap.py'] +
                bootstrap_args, cwd=final_dir)
            self.ninja_exe = find_executable('ninja', final_dir)
            assert self.ninja_exe
