#! python3.3
import sys
import os
import site
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
site_packages = site.getsitepackages()

files_to_locate= [('map_files_inj32.dll',), ('map_files_inj64.dll',)]

include_files=[]

for f in files_to_locate:
    found = False
    for p in sys.path:
        file = os.path.join(p, *f)
        if os.path.exists(file):
            include_files.append((file, ''))
            found = True
            break
    if not found:
        raise Exception("Could not locate '{}'.".format(os.path.join(*f)))


build_options = dict(packages = ['Compilers'],
include_files=include_files,
include_msvcr=True,
)

msi_opts = {'upgrade_code' : '{EC37317C-03E0-4348-8D70-E5D891EE9115}'}

executables = [
    Executable('buildpal_server.py', base='Console')
]

setup(name='BuildPal_Server',
      version = '0.1',
      description = 'BuildPal Server',
      options = dict(build_exe = build_options, bdist_msi=msi_opts),
      executables = executables)
