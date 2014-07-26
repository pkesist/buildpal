import sys
import os
import msilib
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
],
    Icon=[
        ('BuildPalConsoleIcon', msilib.Binary('Resources/Icons/console.ico')),
        ('BuildPalServerIcon', msilib.Binary('Resources/Icons/server.ico')),
        ('BuildPalManagerIcon', msilib.Binary('Resources/Icons/manager.ico'))],

    Shortcut=[
        ('BUILDPAL_ID_0',
        'BuildPalDir',
        'BuildPal Console',
        "TARGETDIR",
        "[TARGETDIR]buildpal.exe",
        "client --run cmd.exe /Q /K echo BuildPal Console (Compiler Substitution)",
        "BuildPal Console - Compiler Substitution",
        None,
        "BuildPalConsoleIcon",
        None,
        None,
        'TARGETDIR'),
        ('BUILDPAL_ID_1',
        'BuildPalDir',
        'BuildPal Console (Experimental)',
        "TARGETDIR",
        "[TARGETDIR]buildpal.exe",
        "client --no-cp --run cmd.exe /Q /K echo BuildPal Console (CreateProcess Hooking)",
        "BuildPal Console - CreateProcess hooking",
        None,
        "BuildPalConsoleIcon",
        None,
        None,
        'TARGETDIR'),
        ('BUILDPAL_ID_2',
        'BuildPalDir',
        'BuildPal Server',
        "TARGETDIR",
        "[TARGETDIR]buildpal.exe",
        "server",
        "BuildPal Server",
        None,
        "BuildPalServerIcon",
        None,
        None,
        'TARGETDIR'),
        ('BUILDPAL_ID_3',
        'BuildPalDir',
        'BuildPal Manager',
        "TARGETDIR",
        "[TARGETDIR]buildpal.exe",
        "manager",
        "BuildPal Manager",
        None,
        "BuildPalManagerIcon",
        None,
        None,
        'TARGETDIR'),
    ]
)

setup(name='BuildPal',
    version='0.2',
    description='BuildPal Distributed Compiler',
    options=dict(
        build_exe=dict(include_msvcr=True, include_files=include_files),
        bdist_msi=dict(upgrade_code='{BC7F4969-6098-4E53-A040-2AEE0683FC9F}', data=msi_data)),
    executables=[
        Executable('Python/buildpal/__main__.py', targetName=exe_file('buildpal'),
            base='Console'),
    ],
)
