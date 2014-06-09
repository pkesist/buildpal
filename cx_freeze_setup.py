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

msi_data = dict(Directory=[
    ('ProgramMenuFolder', 'TARGETDIR', '.'),
    ('BuildPalDir', 'ProgramMenuFolder', 'BuildPal'),
])

setup(name='BuildPal',
    version='0.1',
    description='BuildPal Distributed Compiler',
    options=dict(
        build_exe=dict(include_msvcr=True, include_files=include_files),
        bdist_msi=dict(upgrade_code='{BC7F4969-6098-4E53-A040-2AEE0683FC9F}', data=msi_data)),
    executables=[
        Executable('Python/starter.py', targetName=exe_file('buildpal'),
            base='Console'),
        Executable('Python/client_starter.py', targetName=exe_file('buildpal_client'),
            base='Console'),
        Executable('Python/client_cmd_starter.py', targetName=exe_file('buildpal_console'),
            icon='Documentation/static/console.ico', base='Console',
            shortcutName='BuildPal Console', shortcutDir='BuildPalDir'),
        Executable('Python/manager_starter.py', targetName=exe_file('buildpal_manager'),
            icon='Documentation/static/buildpal2.ico', base='Console',
            shortcutName='BuildPal Manager', shortcutDir='BuildPalDir'),
        Executable('Python/server_starter.py', targetName=exe_file('buildpal_server'),
            icon='Documentation/static/buildpal.ico', base='Console',
            shortcutName='BuildPal Server', shortcutDir='BuildPalDir'),
    ],
)
