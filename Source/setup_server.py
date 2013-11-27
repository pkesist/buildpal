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

buildOptions = dict(packages = ['zmq.backend.cython', 'zmq.utils.garbage', 'Compilers'], excludes = ['zmq.libzmq'],
include_files=[(libzmq_pyd, '')],
)

base = 'Console'

executables = [
    Executable('distribute_server.py', base=base)
]

setup(name='DistriBuild_Server',
      version = '0.1',
      description = 'Server for DistriBuild nodes.',
      options = dict(build_exe = buildOptions),
      executables = executables)
