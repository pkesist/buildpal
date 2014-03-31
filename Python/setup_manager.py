#! python3.3
import sys
import os
import site
from cx_Freeze import setup, Executable

setup(name='BuildPal Manager',
    version = '0.1',
    description = 'BuildPal Manager',
    options = dict(
        build_exe = dict(include_msvcr=True),
        bdist_msi = dict(upgrade_code='{BC7F4969-6098-4E53-A040-2AEE0683FC9F}')),
    executables = [
        Executable('buildpal_manager.py', base='Console', shortcutName = 'BuildPal Manager', shortcutDir='DesktopFolder')
    ],
)
