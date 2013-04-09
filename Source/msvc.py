from cmdline_processing import CmdLineOption, FreeOption
from distribute_client import CompilationDistributer, CompilerInfo

import subprocess

import os
import re
import sys

def find_on_path(executable):
    def test_exe(location):
        return os.path.isfile(location) and os.access(location, os.X_OK)
    direct = os.path.join(os.getcwd(), executable)
    if test_exe(direct):
        return direct
    # If searching PATH we must have only file name, without directory
    # components.
    if os.path.split(executable)[0]:
        return None
    for location in (os.path.join(path, executable) for path in
        os.environ["PATH"].split(os.pathsep)):
        if test_exe(location):
            return location

import subprocess
import tempfile
import os

def get_env_diff(batch, args):
    delimiter = "TEMP_FILE_TESTER_DELIMITER_1351361363416436"
    test_batch_name = None
    with tempfile.NamedTemporaryFile(mode='wt', suffix=".bat", delete=False) as test_batch:
        test_batch_name = test_batch.name
        test_batch.write("""
@echo off
echo {batch}
echo {delimiter}
set
echo {delimiter}
call "{batch}" {args}
echo {delimiter}
set
echo {delimiter}
""".format(batch=os.path.join(os.getcwd(), batch), args=" ".join(a for a in args), delimiter=delimiter))
    to_add={}
    with subprocess.Popen(test_batch_name, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        stdout, stderr = proc.communicate()
        output = stdout.decode()
        output = output.split('\r\n')
        first = output.index(delimiter)
        second = output.index(delimiter, first + 1)
        third  = output.index(delimiter, second + 1)
        fourth = output.index(delimiter, third + 1)
        
        before = output[first + 1 : second - 1]
        after  = output[third + 1 : fourth - 1]
        added = [a for a in after if not a in before]
        removed = [b for b in before if not b in after]
        for a in added:
            eq = a.index('=')
            to_add[a[:eq].upper()] = a[eq+1:]
    try:
        os.remove(test_batch_name)
    except:
        # Ah well.
        pass
    return to_add

class MSVCDistributer(CompilationDistributer):
    def __init__(self):
        super().__init__(preprocess_option=MSVCDistributer.CompilerOption('E', self.esc, None, False),
            obj_name_option=MSVCDistributer.CompilerOption('Fo', self.esc, None, True, False, False),
            compile_no_link_option=MSVCDistributer.CompilerOption('c', self.esc, None, False))
        # Bailout
        for option_desc in self.bailout_options:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.BailoutCategory)
            self.add_option(option)
        # Preprocessing
        for option_desc in self.preprocessing_options:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.PreprocessingCategory)
            self.add_option(option)
        # Compilation
        for option_desc in self.compilation_options:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.CompilationCategory)
            self.add_option(option)
        # PCH options. Recognized, but ignored.
        for option_desc in self.pch_options:
            self.add_option(MSVCDistributer.CompilerOption(*option_desc))
        # Both preprocessing and compilation.
        for option_desc in self.preprocess_and_compile:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.PreprocessingCategory)
            option.add_category(CompilationDistributer.CompilationCategory)
            self.add_option(option)
        # Always.
        for option_desc in self.always:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.PreprocessingCategory)
            option.add_category(CompilationDistributer.CompilationCategory)
            option.add_category(CompilationDistributer.LinkingCategory)
            self.add_option(option)

    def requires_preprocessing(self, input):
        # This should be handled better.
        # Currently we expect there is no /TC, /TP,
        # /Tc or /Tp options on the command line
        return os.path.splitext(input)[1].lower() in ['.c', '.cpp', '.cxx']

    def compiler_info(self, executable):
        abs = find_on_path(executable)
        if not abs:
            raise RuntimeError("Cannot find compiler executable '{}'.".format(executable))
        with subprocess.Popen(abs, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            stdout, stderr = proc.communicate()
        m = re.search(b'C/C\+\+ Optimizing Compiler Version (?P<ver>.*) for (?P<plat>.*)\r\n', stderr)
        if not m:
            raise EnvironmentError("Failed to identify compiler - unexpected output.")
        version = (m.group('ver'), m.group('plat'))
        assert version in self.compiler_versions
        return CompilerInfo("msvc", os.path.split(executable)[1], os.path.getsize(abs), version)

    @classmethod
    def setup_compiler(cls, compiler_info):
        compiler_id = compiler_info.id()
        info = cls.compiler_versions.get(compiler_id)
        if not info:
            return None
        script = r'c:\Program Files (x86)\Microsoft Visual Studio {}.0\VC\vcvarsall.bat'.format(info[0])
        to_add = get_env_diff(script, [info[1]])
        def run_compiler(command, to_add):
            env = dict(os.environ)
            env.update(to_add)
            with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        return lambda command : run_compiler(command, to_add)

    esc = ['/', '-']
    
    compiler_versions = {
        (b'15.00.30729.01', b'80x86') : (9 , 'x86'  ), # msvc9
        (b'15.00.30729.01', b'x64'  ) : (9 , 'amd64'), # msvc9 x64
        (b'16.00.40219.01', b'80x86') : (10, 'x86'  ), # msvc10
        (b'16.00.40219.01', b'x64'  ) : (10, 'amd64'), # msvc10 x64
        (b'17.00.50727.1' , b'x86'  ) : (11, 'x86'  ), # msvc11
        (b'17.00.50727.1' , b'x64'  ) : (11, 'amd64'), # msvc11 x64
    }

    # If we run into these just run the damn thing locally
    bailout_options = [
        ['E' , esc, None, False],
        ['EP', esc, None, False],
        ['P' , esc, None, False],
        ['Zg', esc, None, False],
        ['Zs', esc, None, False],
    ]

    preprocessing_options = [
        ['AI', esc, None, True , False, False],
        ['FU', esc, None, True , False, False],
        ['C' , esc, None, False              ],
        ['D' , esc, None, True , False, False],
        ['Fx', esc, None, False              ],
        ['FI', esc, None, True , False, False],
        ['U' , esc, None, True , False, False],
        ['u' , esc, None, False              ],
        ['I' , esc, None, True , False, False],
        ['X' , esc, None, False              ],
    ]

    pch_options = [
        ['Fp', esc, None, True , False, False],
        ['Yc', esc, None, True , False, False],
        ['Yl', esc, None, True , False, False],
        ['Yu', esc, None, True , False, False],
        ['Y-', esc, None, False              ]
    ]

    preprocess_and_compile = [
        # These affect MSVC #pragmas, so we need them while preprocessing.
        # TODO: Check if they are really needed for compilation.
        ['EH' , esc, None, True, False, False],
        ['MD' , esc, None, False             ],
        ['MT' , esc, None, False             ],
        ['MDd', esc, None, False             ],
        ['MTd', esc, None, False             ],
    ]

    always = [
        ['nologo', esc, None, False],
    ]

    compilation_options = [
        ['O1'                   , esc, None, False              ],
        ['O2'                   , esc, None, False              ],
        ['Ob'                   , esc, None, True , False, False],
        ['Od'                   , esc, None, False              ],
        ['Og'                   , esc, None, False              ],
        ['Oi'                   , esc, '-' , False              ],
        ['Os'                   , esc, None, False              ],
        ['Ot'                   , esc, None, False              ],
        ['Ox'                   , esc, None, False              ],
        ['Oy'                   , esc, '-' , False              ],
        ['O'                    , esc, None, True , False, False],
        ['GF'                   , esc, None, False              ],
        ['Gm'                   , esc, '-' , False              ],
        ['Gy'                   , esc, '-' , False              ],
        ['GS'                   , esc, '-' , False              ],
        ['GR'                   , esc, '-' , False              ],
        ['GX'                   , esc, '-' , False              ],
        ['fp'                   , esc, None, True, False, False ],
        ['Qfast_transcendentals', esc, None, False              ],
        ['GL'                   , esc, '-' , False              ],
        ['GA'                   , esc, None, False              ],
        ['Ge'                   , esc, None, False              ],
        ['Gs'                   , esc, None, True, False, False ],
        ['Gh'                   , esc, None, False              ],
        ['GH'                   , esc, None, False              ],
        ['GT'                   , esc, None, False              ],
        ['RTC1'                 , esc, None, False              ],
        ['RTCc'                 , esc, None, False              ],
        ['RTCs'                 , esc, None, False              ],
        ['RTCu'                 , esc, None, False              ],
        ['clr'                  , esc, None, True, False, False ],
        ['Gd'                   , esc, None, False              ],
        ['Gr'                   , esc, None, False              ],
        ['Gz'                   , esc, None, False              ],
        ['GZ'                   , esc, None, False              ],
        ['QIfist'               , esc, '-' , False              ],
        ['hotpatch'             , esc, None, False              ],
        ['arch'                 , esc, None, True , False, False],
        ['Qimprecise_fwaits'    , esc, None, False              ],
        ['Fa'                   , esc, None, True , False, False],
        ['FA'                   , esc, None, True , False, False],
        ['Fd'                   , esc, None, True , False, False],
        ['Fe'                   , esc, None, True , False, False],
        ['Fm'                   , esc, None, True , False, False],
        ['Fr'                   , esc, None, True , False, False],
        ['FR'                   , esc, None, True , False, False],
        ['doc'                  , esc, None, True , False, False],
        ['Zi'                   , esc, None, False              ],
        ['Z7'                   , esc, None, False              ],
        ['Zp'                   , esc, None, True , False, False],
        ['Za'                   , esc, None, False              ],
        ['Ze'                   , esc, None, False              ],
        ['Zl'                   , esc, None, False              ],
        ['vd'                   , esc, None, True , False, False],
        ['vm'                   , esc, None, True , False, False],
        ['Zc'                   , esc, None, True , False, False],
        ['ZI'                   , esc, None, False              ],
        ['openmp'               , esc, None, False              ],
        ['?'                    , esc, None, False              ],
        ['help'                 , esc, None, False              ],
        ['bigobj'               , esc, None, False              ],
        ['errorReport'          , esc, None, True , False, False],
        ['FC'                   , esc, None, False              ],
        ['H'                    , esc, None, True , False, False],
        ['J'                    , esc, None, False              ],
        ['MP'                   , esc, None, True , False, False],
        ['showIncludes'         , esc, None, False              ],
        ['Tc'                   , esc, None, True , False, False],
        ['Tp'                   , esc, None, True , False, False],
        ['TC'                   , esc, None, False              ],
        ['TP'                   , esc, None, False              ],
        ['V'                    , esc, None, True , False, False],
        ['w'                    , esc, None, False              ],
        ['wd'                   , esc, None, True , False, False],
        ['we'                   , esc, None, True , False, False],
        ['wo'                   , esc, None, True , False, False],
        ['w'                    , esc, None, True , False, False],
        ['Wall'                 , esc, None, False              ],
        ['WL'                   , esc, None, False              ],
        ['WX'                   , esc, None, False              ],
        ['W'                    , esc, None, True , False, False],
        ['Yd'                   , esc, None, False              ],
        ['Zm'                   , esc, None, True , False, False],
        ['Wp64'                 , esc, None, False              ],
        ['LD'                   , esc, None, False              ],
        ['LDd'                  , esc, None, False              ],
        ['LN'                   , esc, None, False              ],
        ['F'                    , esc, None, True , False, False],
        ['link'                 , esc, None, False              ],
        ['analyze'              , esc, None, True , False, False]
    ]

if __name__ == "__main__":
    distributer = MSVCDistributer()
    distributer.execute(sys.argv[1:])
