import sys
import os
import subprocess
import distutils.ccompiler

def process_asm(filename_base, output_dir):
    with subprocess.Popen(['gawk', '-f', 'asm_to_inc.awk', '-v',
        'func_name=runDLL', '-v', 'indent=0',
        '{}.cod'.format(filename_base)],
        stdout=subprocess.PIPE) as proc:
        stdout, _ = proc.communicate()
    with open(os.path.join(output_dir, '{}.inc'.format(filename_base)), 'wb') as file:
        file.write(stdout)
    os.remove('{}.cod'.format(filename_base))

output_dir = sys.argv[1]
os.makedirs(output_dir, exist_ok=True)

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win32')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader32.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
process_asm('loader32', output_dir)

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win-amd64')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader64.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
process_asm('loader64', output_dir)




