import sys
import os
from cx_Freeze import setup, Executable

def exe_file(name):
    if os.name == 'nt':
        return name + '.exe'
    return name

include_files = [('LICENSE.txt', ''), ('COPYRIGHT.txt', '')]
files_to_locate = [
    ('map_files_inj32.dll',),
    ('map_files_inj64.dll',),
    ('bp_cli_inj32.dll',),
    ('bp_cli_inj64.dll',),
    ('bp_cl.exe',),
]
for f in files_to_locate:
    found = False
    for file in (os.path.join(p, *f) for p in sys.path):
        if os.path.exists(file):
            include_files.append((file, ''))
            found = True
            break
    if not found:
        raise Exception("Could not locate '{}'.".format(os.path.join(*f)))

setup(name='BuildPal',
    version = '0.1',
    description = 'BuildPal Distributed Compiler',
    options = dict(
        build_exe = dict(include_msvcr=True, include_files=include_files),
        bdist_msi = dict(upgrade_code='{BC7F4969-6098-4E53-A040-2AEE0683FC9F}')),
    executables = [
        Executable('Python/starter.py', targetName=exe_file('buildpal'),
            icon='Documentation/static/buildpal.ico', base='Console'),
        Executable('Python/server_starter.py', targetName=exe_file('buildpal_server'),
            icon='Documentation/static/buildpal.ico', base='Console',
            shortcutName='BuildPal Server', shortcutDir='DesktopFolder'),
        Executable('Python/manager_starter.py', targetName=exe_file('buildpal_client'),
            icon='Documentation/static/buildpal2.ico', base='Console',
            shortcutName = 'BuildPal Client Manager', shortcutDir='DesktopFolder')
    ],
)
