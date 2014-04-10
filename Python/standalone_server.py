import sys
import os
from cx_Freeze import setup, Executable

files_to_locate = [('map_files_inj32.dll',), ('map_files_inj64.dll',)]

include_files = []

for f in files_to_locate:
    found = False
    for file in (os.path.join(p, *f) for p in sys.path):
        if os.path.exists(file):
            include_files.append((file, ''))
            found = True
            break
    if not found:
        raise Exception("Could not locate '{}'.".format(os.path.join(*f)))

def exe_file(name):
    if os.name == 'nt':
        return name + '.exe'
    return name

packages = []
includes = []
executables = [
    Executable('server_starter.py', targetName=exe_file('buildpal_server'),
        icon='../Documentation/static/buildpal.ico',
        base='Console', shortcutName='BuildPal Server',
        shortcutDir='DesktopFolder'),
]

include_service = False
if include_service:
    executables.append(Executable('server_svc_config.py',
        targetName=exe_file('buildpal_server_svc'),
        icon='../Documentation/static/buildpal.ico',
        base='Win32Service'))
    packages.append('cx_Logging')
    includes.append('server_svc_handler')

setup(name='BuildPal Server',
    version = '0.1',
    description = 'BuildPal Server',
    options = dict(
        build_exe=dict(include_files=include_files, include_msvcr=True,
            packages=packages, includes=includes),
        bdist_msi=dict(upgrade_code='{EC37317C-03E0-4348-8D70-E5D891EE9115}')
    ),
    executables = executables
)
