#! python3.3
import sys
import os
import site
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
site_packages = site.getsitepackages()

build_options = dict(packages = ['Compilers'],
    include_msvcr=True,
)

msi_opts = {'upgrade_code' : '{BC7F4969-6098-4E53-A040-2AEE0683FC9F}'}

executables = [
    Executable('buildpal_manager.py', base='Win32GUI')
]

setup(name='BuildPal Manager',
      version = '0.1',
      description = 'BuildPal Manager',
      options = dict(build_exe = build_options, bdist_msi=msi_opts),
      executables = executables)
