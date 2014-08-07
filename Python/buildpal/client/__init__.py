import buildpal_client

import os
import subprocess
import sys
import winreg

def detect_compilers():
    versions = ('9.0', '10.0', '11.0', '12.0')
    compiler_dirs = ('bin', 'bin\\amd64', 'bin\\x86_amd64', 'bin\\x86_ia64')
    win32subkey = "WOW6432Node\\" if sys.maxsize > 2**32 else ""

    for kind in ('VisualStudio', 'VCExpress'):
        for version in versions:
            try:
                key_path = r'SOFTWARE\{}Microsoft\{}\{}\Setup\VC'.format(
                    win32subkey, kind, version)
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    dir = winreg.QueryValueEx(key, 'ProductDir')[0]
                    for rel_dir in compiler_dirs:
                        compiler_path = os.path.join(dir, rel_dir, 'cl.exe')
                        if os.path.exists(compiler_path):
                            yield compiler_path
            except FileNotFoundError:
                pass
    
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\BuildPal') as key:
            executables = winreg.QueryValueEx(key, 'ExtraCompilers')[0]
            for exe in executables:
                yield exe
    except FileNotFoundError:
        pass

def register_compiler_executable(exe):
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\BuildPal') as key:
        if not os.path.exists(exe):
            raise FileNotFoundError(exe)
        try:
            executables = winreg.QueryValueEx(key, 'ExtraCompilers')[0]
        except FileNotFoundError:
            executables = []
        value = os.path.normcase(os.path.normpath(os.path.abspath(exe)))
        if value in executables:
            print("Compiler '{}' already registered.".format(exe))
            return
        executables.append(value)
        winreg.SetValueEx(key, 'ExtraCompilers', 0, winreg.REG_MULTI_SZ, executables)

def unregister_compiler_executable(exe):
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\BuildPal') as key:
        try:
            executables = winreg.QueryValueEx(key, 'ExtraCompilers')[0]
        except FileNotFoundError:
            executables = []
        executables.remove(os.path.normcase(os.path.normpath(os.path.abspath(exe))))
        winreg.SetValueEx(key, 'ExtraCompilers', 0, winreg.REG_MULTI_SZ, executables)

def setup_hooks(port_name, replacement=''):
    for compiler in detect_compilers():
        buildpal_client.register_compiler(compiler, replacement)
    buildpal_client.set_port_name(port_name)
    return buildpal_client.create_process


def find_bp_cl():
    curdir = os.path.dirname(__file__)
    while True:
        bp_cl = os.path.join(curdir, 'bp_cl.exe')
        if os.path.exists(bp_cl):
            return bp_cl
        curdir = os.path.dirname(curdir)
        if not curdir:
            raise EnvironmentError("Could not find 'bp_cl.exe'.")

def main(opts):
    must_call_run = True
    for exe in opts.register_compiler or []:
        register_compiler_executable(exe)
        must_call_run = False

    for exe in opts.unregister_compiler or []:
        unregister_compiler_executable(exe)
        must_call_run = False

    if opts.list_compilers:
        print("-------------------")
        print("Detected compilers:")
        print("-------------------")
        for compiler in detect_compilers():
            print(compiler)
        print("-------------------")
        must_call_run = False

    if opts.run is None:
        if must_call_run:
            raise Exception("Command not specified")
        return 0

    setup_hooks(opts.connect, '' if opts.no_cp else find_bp_cl())

    class OverrideCreateProcess:
        def __enter__(self):
            buildpal_client.enable_hooks()

        def __exit__(self, exc_type, exc_value, traceback):
            buildpal_client.disable_hooks()

    with OverrideCreateProcess():
        return subprocess.call(opts.run)
