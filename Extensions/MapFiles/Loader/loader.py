import os
import subprocess
import distutils.ccompiler
import distutils.msvc9compiler

distutils.msvc9compiler.VERSION = 11.0

def process_asm(filename_base):
    with subprocess.Popen(['gawk', '-f', 'loader.awk', '-v',
        'func_name=runDLL', '-v', 'indent=0',
        '{}.cod'.format(filename_base)],
        stdout=subprocess.PIPE) as proc:
        stdout, _ = proc.communicate()
    with open('{}.inc'.format(filename_base), 'wb') as file:
        file.write(stdout)
    os.remove('{}.cod'.format(filename_base))

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win32')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader32.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
process_asm('loader32')

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win-amd64')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader64.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
process_asm('loader64')




