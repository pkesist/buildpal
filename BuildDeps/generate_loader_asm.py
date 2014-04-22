import sys
import os
import subprocess
import distutils.ccompiler

from .asm_to_inc import convert_to_c_array

def asm_to_inc(filename_base, output_dir, tmp_dir):
    with open('{}.cod'.format(os.path.join(tmp_dir, filename_base)), 'r') as fin, \
        open('{}.inc'.format(os.path.join(output_dir, filename_base)), 'w') as fout:
        convert_to_c_array(fin, fout, 'runDLL')

def main(src_file, output_dir, tmp_dir):
    os.makedirs(output_dir, exist_ok=True)
    src_file = os.path.abspath(src_file)

    compiler = distutils.ccompiler.new_compiler(compiler='msvc')
    compiler.initialize('win32')
    subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader32.cod', '/FAsc', src_file], cwd=tmp_dir)
    asm_to_inc('loader32', output_dir, tmp_dir)

    compiler = distutils.ccompiler.new_compiler(compiler='msvc')
    compiler.initialize('win-amd64')
    subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot', '/Faloader64.cod', '/FAsc', src_file], cwd=tmp_dir)
    asm_to_inc('loader64', output_dir, tmp_dir)
