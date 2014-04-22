import sys
import os
import subprocess
import distutils.ccompiler

from asm_to_inc import convert_to_c_array

def asm_to_inc(filename_base, output_dir):
    with open('{}.cod'.format(filename_base), 'r') as fin, \
        open('{}.inc'.format(os.path.join(output_dir, filename_base)), 'w') as fout:
        convert_to_c_array(fin, fout, 'runDLL')

output_dir = sys.argv[1]
os.makedirs(output_dir, exist_ok=True)

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win32')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader32.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
asm_to_inc('loader32', output_dir)
os.remove('loader32.cod')

compiler = distutils.ccompiler.new_compiler(compiler='msvc')
compiler.initialize('win-amd64')
subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader64.cod', '/FAsc', 'loader.cpp'])
os.remove('loader.obj')
asm_to_inc('loader64', output_dir)
os.remove('loader64.cod')
