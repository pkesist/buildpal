import sys
import os
from cx_Freeze import setup, Executable

client_exe = os.path.abspath(os.path.join('..', 'bp_cl.exe'))
if not os.path.exists(client_exe):
    raise Exception("Could not locate '{}'.".format(client_exe))

def exe_file(name):
    if os.name == 'nt':
        return name + '.exe'
    return name

setup(name='BuildPal Manager',
    version = '0.1',
    description = 'BuildPal Manager',
    options = dict(
        build_exe = dict(include_msvcr=True, include_files=[(client_exe, '')]),
        bdist_msi = dict(upgrade_code='{BC7F4969-6098-4E53-A040-2AEE0683FC9F}')),
    executables = [
        Executable('manager_starter.py', targetName=exe_file('buildpal_manager'),
            icon='../Documentation/static/buildpal2.ico', base='Console',
            shortcutName = 'BuildPal Manager', shortcutDir='DesktopFolder')
    ],
)