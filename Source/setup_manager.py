#! python3.3
import sys
import os
import site
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
site_packages = site.getsitepackages()

possible_libzmq_locations = [os.path.join(s, 'zmq', 'libzmq.pyd') for s in site_packages]
libzmq_pyd = None
for p in (os.path.join(s, 'zmq', 'libzmq.pyd') for s in site_packages):
    if os.path.exists(p):
        libzmq_pyd = p
        break
if not libzmq_pyd:
    raise Exception("Could not find 'libzmq.pyd'.")

build_options = dict(packages = ['zmq.backend.cython', 'zmq.utils.garbage', 'Compilers'], excludes = ['zmq.libzmq'],
    include_files=[(libzmq_pyd, '')],
    include_msvcr=True,
)

msi_opts = {'upgrade_code' : '{BC7F4969-6098-4E53-A040-2AEE0683FC9F}'}

base = 'Console'

executables = [
    Executable('distribute_manager.py', base=base)
]

setup(name='BuildPal_Manager',
      version = '0.1',
      description = 'BuildPal Manager',
      options = dict(build_exe = build_options, bdist_msi=msi_opts),
      executables = executables)
