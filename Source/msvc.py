from cmdline_processing import CmdLineOption, FreeOption
from distribute_client import CompilationDistributer, CompilerInfo
from utils import get_batch_file_environment_side_effects, TempFile

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
def simple(name, macros=None): 
    result = CompilationDistributer.CompilerOption(name, esc, None, False)
    if macros:
        for macro in macros:
            result.add_macro(macro)
    return result

def simple_w_minus(name, macros=None):
    result = CompilationDistributer.CompilerOption(name, esc, '-', False)
    if macros:
        for macro in macros:
            result.add_macro(macro)
    return result

def with_param(name, macros=None):
    result = CompilationDistributer.CompilerOption(name, esc, None, True, False, False)
    if macros:
        for macro in macros:
            result.add_macro(macro)
    return result


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
        macros = ('_MSC_VER', '_MSC_FULL_VER', '_CPPLIB_VER', '_HAS_TR1',
            '_WIN32', '_WIN64', '_M_IX86', '_M_IA64', '_M_MPPC', '_M_MRX000',
            '_M_PPC', '_M_X64', '_INTEGRAL_MAX_BITS', '_HAS_ITERATOR_DEBUGGING')

        with TempFile(suffix='.cpp') as tempfile:
            with tempfile.open("wt") as file:
                lines = []
                # Need a STL header to get _CPPLIB_VER
                lines.append("#include <utility>\n")
                # Stolen from Boost.PP
                lines.append("#define STR(x) STR_I((x))\n")
                lines.append("#define STR_I(x) STR_II x\n")
                lines.append("#define STR_II(x) #x\n")
                for symbol in macros:
                    lines.append('#ifndef {m}\n'.format(m=symbol))
                    lines.append('#pragma message("_M_A_C_R_O_ /{m}/__NOT_DEFINED__/")\n'.format(m=symbol))
                    lines.append('#else\n')
                    lines.append('#pragma message("_M_A_C_R_O_ /{m}/" STR({m}) "/")\n'.format(m=symbol))
                    lines.append('#endif\n')
                file.writelines(lines)
            proc = subprocess.Popen([abs, '-c', tempfile.filename()], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = proc.communicate()
            output = stdout.split(b'\r\n')
            macros = []
            for line in output:
                m = re.match(b'^_M_A_C_R_O_ /(.*)/(.*)/$', line)
                if m:
                    if m.group(2) == b'__NOT_DEFINED__':
                        continue
                    macros.append('{}={}'.format(m.group(1).decode(), m.group(2).decode()))
            m = re.search(b'C/C\+\+ Optimizing Compiler Version (?P<ver>.*) for (?P<plat>.*)\r\n', stderr)
            if not m:
                raise EnvironmentError("Failed to identify compiler - unexpected output.")
            version = (m.group('ver'), m.group('plat'))
            assert version in self.compiler_versions
            return CompilerInfo("msvc", os.path.split(executable)[1], os.path.getsize(abs), version, macros)

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
                except Exception:
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

    def compiler_option_macros(self, tokens):
        result = []
        add_extensions = True
        for token in (token for token in tokens
            if type(token.option) == CompilationDistributer.CompilerOption and
            token.option.test_category(CompilationDistributer.PreprocessingCategory)):
            option = token.option
            if not option:
                continue
            if option.name() == 'Za':
                add_extensions = False
            if option.name() == 'Zi':
                add_extensions = True
            result += token.option.get_macros(token.val)
        if add_extensions:
            result.append('_MSC_EXTENSIONS=1')
        return result



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
        simple('E' ), simple('EP'), simple('P' ),
        simple('Zg'), simple('Zs')]

    preprocessing_options = [
        with_param('AI'), with_param('FU'), with_param('D' ), with_param('FI'),
        with_param('U' ), with_param('I' ), simple    ('C' ), simple    ('Fx'),
        simple    ('u' ), simple    ('X' )]

    pch_options = [
        with_param('Fp'), with_param('Yc'), with_param('Yl'), with_param('Yu'),
        simple    ('Y-')]

    preprocess_and_compile = [
        # These affect preprocessor.
        with_param('EH' , ['_CPPUNWIND']),
        simple    ('MD' , ['_MT', '_DLL']),
        simple    ('MT' , ['_MT']),
        simple    ('MDd', ['_MT', '_DLL', '_DEBUG']),
        simple    ('MTd', ['_MT', '_DEBUG']),
        simple_w_minus('GR', ['_CPPRTTI']),
        simple_w_minus('GX', ['_CPPUNWIND']),
        simple    ('RTC1', ['__MSVC_RUNTIME_CHECKS']),
        simple    ('RTCc', ['__MSVC_RUNTIME_CHECKS']),
        simple    ('RTCs', ['__MSVC_RUNTIME_CHECKS']),
        simple    ('RTCu', ['__MSVC_RUNTIME_CHECKS']),
        with_param('clr', ['__cplusplus_cli=200406']),
        simple    ('Za'), # These two require special handling.
        simple    ('Ze'), # /Ze is default, and must define _MSC_EXTENSIONS
        simple    ('Zl', ['_VC_NODEFAULTLIB']),
        with_param('Zc', [lambda val : '_NATIVE_WCHAR_T_DEFINED' if 'wchar_t' in val else None]),
        simple    ('openmp', ['_OPENMP']),
        simple    ('Wp64', ['_Wp64']),
        simple    ('LDd', ['_DEBUG']),
    ]

    always = [ simple('nologo') ]

    compilation_options = [
        simple        ('O1'), simple        ('O2'), with_param    ('Ob'), simple      ('Od'),
        simple        ('Og'), simple_w_minus('Oi'), simple        ('Os'), simple      ('Ot'),
        simple        ('Ox'), simple_w_minus('Oy'), with_param    ('O' ), simple      ('GF'),
        simple_w_minus('Gm'), simple_w_minus('Gy'), simple_w_minus('GS'), with_param  ('fp'),
        simple        ('Qfast_transcendentals')   , simple_w_minus('GL'), simple      ('GA'),
        simple        ('Ge'), with_param    ('Gs'), simple        ('Gh'), simple      ('GH'),
        simple        ('GT'), simple        ('Gd'), simple        ('Gr'), simple      ('Gz'),
        simple        ('GZ'), simple_w_minus('QIfist'), simple('hotpatch'), with_param('arch'),
        simple        ('Qimprecise_fwaits')       , with_param    ('Fa'), with_param  ('FA'),
        with_param    ('Fd'), with_param    ('Fe'), with_param    ('Fm'), with_param  ('Fr'),
        with_param    ('FR'), with_param   ('doc'), simple        ('Zi'), simple      ('Z7'),
        with_param    ('Zp'), with_param    ('vd'), with_param    ('vm'), simple      ('ZI'),
        simple        ('?'),  simple      ('help'), simple    ('bigobj'), with_param  ('errorReport'),
        simple        ('FC'), with_param    ('H') , simple         ('J'), with_param  ('MP'),
        simple        ('showIncludes')            , with_param    ('Tc'), with_param  ('Tp'),
        simple        ('TC'), simple        ('TP'), with_param     ('V'), simple      ('w'),
        with_param    ('wd'), with_param    ('we'), with_param    ('wo'), with_param  ('w'),
        simple      ('Wall'), simple        ('WL'), simple        ('WX'), with_param  ('W'),
        simple        ('Yd'), with_param    ('Zm'), simple        ('LD'), simple      ('LN'),
        with_param     ('F'), simple      ('link'), with_param('analyze')]

if __name__ == "__main__":
    distributer = MSVCDistributer()
    distributer.execute(sys.argv[1:])
