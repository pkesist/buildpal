from cmdline_processing import CmdLineOption, FreeOption
from distribute_client import CompilationDistributer, CompilerInfo
from utils import get_batch_file_environment_side_effects

import subprocess

import os
import re
import sys
import winreg

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

esc = ['/', '-']
def simple(name): return CompilationDistributer.CompilerOption(name, esc, None, False)
def simple_w_minus(name): return CompilationDistributer.CompilerOption(name, esc, '-', False)
def with_param(name): return CompilationDistributer.CompilerOption(name, esc, None, True, False, False)


class MSVCDistributer(CompilationDistributer):
    def preprocess_option(self): return self.__preprocess_option
    def object_name_option(self): return self.__object_name_option
    def compile_no_link_option(self): return self.__compile_no_link_option
    def include_file_option(self): return self.__include_file_option
    def define_option(self): return self.__define_option

    def __init__(self):
        self.__preprocess_option = simple('E')
        self.__object_name_option = with_param('Fo')
        self.__compile_no_link_option = simple('c')
        self.__include_file_option = with_param('I')
        self.__define_option = with_param('D')
        super(MSVCDistributer, self).__init__()

        # Bailout
        for option in self.bailout_options:
            option.add_category(MSVCDistributer.BailoutCategory)
            self.add_option(option)
        # Preprocessing
        for option in self.preprocessing_options:
            option.add_category(MSVCDistributer.PreprocessingCategory)
            self.add_option(option)
        # Compilation
        for option in self.compilation_options:
            option.add_category(MSVCDistributer.CompilationCategory)
            self.add_option(option)
        # PCH options. Recognized, but ignored.
        for option in self.pch_options:
            self.add_option(option)
        # Both preprocessing and compilation.
        for option in self.preprocess_and_compile:
            option.add_category(MSVCDistributer.PreprocessingCategory)
            option.add_category(MSVCDistributer.CompilationCategory)
            self.add_option(option)
        # Always.
        for option in self.always:
            option.add_category(MSVCDistributer.PreprocessingCategory)
            option.add_category(MSVCDistributer.CompilationCategory)
            option.add_category(MSVCDistributer.LinkingCategory)
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

        location = None
        for element in ['', 'Wow6432Node\\']:
            for type in ['VisualStudio', 'VCExpress']:
                key = "SOFTWARE\\{}Microsoft\\{}\\{}.0\\Setup\\VC".format(element, type, info[0])
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as reg_key:
                        location = winreg.QueryValueEx(reg_key, "ProductDir")[0]
                        break
                except:
                    pass
        if not location:
            return None
        script = os.path.join(location, 'vcvarsall.bat')
        if not os.path.exists(script):
            return None
        to_add = get_batch_file_environment_side_effects(script, [info[1]])
        def run_compiler(command, to_add):
            env = dict(os.environ)
            env.update(to_add)
            with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        return lambda command : run_compiler(command, to_add)

    compiler_versions = {
        (b'15.00.30729.01', b'80x86') : (9 , 'x86'  ), # msvc9
        (b'15.00.30729.01', b'x64'  ) : (9 , 'amd64'), # msvc9 x64
        (b'16.00.40219.01', b'80x86') : (10, 'x86'  ), # msvc10
        (b'16.00.40219.01', b'x64'  ) : (10, 'amd64'), # msvc10 x64
        (b'17.00.50727.1' , b'x86'  ) : (11, 'x86'  ), # msvc11
        (b'17.00.50727.1' , b'x64'  ) : (11, 'amd64'), # msvc11 x64
    }

    bailout_options = [
        # If we run into these just run the damn thing locally
        simple('E' ),
        simple('EP'),
        simple('P' ),
        simple('Zg'),
        simple('Zs'),
    ]

    preprocessing_options = [
        with_param('AI'),
        with_param('FU'),
        with_param('D' ),
        with_param('FI'),
        with_param('U' ),
        with_param('I' ),
        simple    ('C' ),
        simple    ('Fx'),
        simple    ('u' ),
        simple    ('X' ),
    ]

    pch_options = [
        with_param('Fp'),
        with_param('Yc'),
        with_param('Yl'),
        with_param('Yu'),
        simple    ('Y-')
    ]

    preprocess_and_compile = [
        # These affect MSVC #pragmas, so we need them while preprocessing.
        # TODO: Check if they are really needed for compilation.
        with_param('EH' ), #defines _CPPUNWIND
        simple    ('MD' ), #defines _MT, _DLL
        simple    ('MT' ), #defines _MT
        simple    ('MDd'), #defines _MT, _DLL, _DEBUG
        simple    ('MTd'), #defines _MT, _DEBUG
    ]

    always = [
        simple('nologo')
    ]

    compilation_options = [
        simple        ('O1'                   ),
        simple        ('O2'                   ),
        with_param    ('Ob'                   ),
        simple        ('Od'                   ),
        simple        ('Og'                   ),
        simple_w_minus('Oi'                   ),
        simple        ('Os'                   ),
        simple        ('Ot'                   ),
        simple        ('Ox'                   ),
        simple_w_minus('Oy'                   ),
        with_param    ('O'                    ),
        simple        ('GF'                   ),
        simple_w_minus('Gm'                   ),
        simple_w_minus('Gy'                   ),
        simple_w_minus('GS'                   ),
        simple_w_minus('GR'                   ),
        simple_w_minus('GX'                   ),
        with_param    ('fp'                   ),
        simple        ('Qfast_transcendentals'),
        simple_w_minus('GL'                   ),
        simple        ('GA'                   ),
        simple        ('Ge'                   ),
        with_param    ('Gs'                   ),
        simple        ('Gh'                   ),
        simple        ('GH'                   ),
        simple        ('GT'                   ),
        simple        ('RTC1'                 ),
        simple        ('RTCc'                 ),
        simple        ('RTCs'                 ),
        simple        ('RTCu'                 ),
        with_param    ('clr'                  ),
        simple        ('Gd'                   ),
        simple        ('Gr'                   ),
        simple        ('Gz'                   ),
        simple        ('GZ'                   ),
        simple_w_minus('QIfist'               ),
        simple        ('hotpatch'             ),
        with_param    ('arch'                 ),
        simple        ('Qimprecise_fwaits'    ),
        with_param    ('Fa'                   ),
        with_param    ('FA'                   ),
        with_param    ('Fd'                   ),
        with_param    ('Fe'                   ),
        with_param    ('Fm'                   ),
        with_param    ('Fr'                   ),
        with_param    ('FR'                   ),
        with_param    ('doc'                  ),
        simple        ('Zi'                   ),
        simple        ('Z7'                   ),
        with_param    ('Zp'                   ),
        simple        ('Za'                   ),
        simple        ('Ze'                   ),
        simple        ('Zl'                   ),
        with_param    ('vd'                   ),
        with_param    ('vm'                   ),
        with_param    ('Zc'                   ),
        simple        ('ZI'                   ),
        simple        ('openmp'               ),
        simple        ('?'                    ),
        simple        ('help'                 ),
        simple        ('bigobj'               ),
        with_param    ('errorReport'          ),
        simple        ('FC'                   ),
        with_param    ('H'                    ),
        simple        ('J'                    ),
        with_param    ('MP'                   ),
        simple        ('showIncludes'         ),
        with_param    ('Tc'                   ),
        with_param    ('Tp'                   ),
        simple        ('TC'                   ),
        simple        ('TP'                   ),
        with_param    ('V'                    ),
        simple        ('w'                    ),
        with_param    ('wd'                   ),
        with_param    ('we'                   ),
        with_param    ('wo'                   ),
        with_param    ('w'                    ),
        simple        ('Wall'                 ),
        simple        ('WL'                   ),
        simple        ('WX'                   ),
        with_param    ('W'                    ),
        simple        ('Yd'                   ),
        with_param    ('Zm'                   ),
        simple        ('Wp64'                 ),
        simple        ('LD'                   ),
        simple        ('LDd'                  ),
        simple        ('LN'                   ),
        with_param    ('F'                    ),
        simple        ('link'                 ),
        with_param    ('analyze'              ),
    ]

if __name__ == "__main__":
    distributer = MSVCDistributer()
    distributer.execute(sys.argv[1:])
