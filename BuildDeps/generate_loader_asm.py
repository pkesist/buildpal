import sys
import os
import subprocess
import distutils.ccompiler
from distutils.dep_util import newer

from .asm_to_inc import convert_to_c_array

def generate_code(target_type, src_file, output_file, workdir):
    if not newer(src_file, output_file):
        return
    compiler = distutils.ccompiler.new_compiler(compiler='msvc')
    compiler.initialize(target_type)
    cod_file = os.path.splitext(output_file)[0] + '.cod'
    subprocess.check_call([compiler.cc, '/nologo', '/c', '/Ox', '/Ot',
        '/Fa{}'.format(cod_file), '/FAsc', os.path.abspath(src_file)],
         cwd=workdir)
    with open(cod_file, 'r') as fin, open(output_file, 'w') as fout:
        convert_to_c_array(fin, fout, 'runDLL')
