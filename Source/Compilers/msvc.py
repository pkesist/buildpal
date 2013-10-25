from .cmdline_processing import *

from Common import get_batch_file_environment_side_effects

import subprocess

import os
import re
import sys
import tempfile
import winreg

def simple(name, macros=[]): 
    result = CompilerOption(name, suff=None, has_arg=False)
    for macro in macros:
        result.add_macro(macro)
    return result

def simple_w_minus(name, macros=[]):
    result = CompilerOption(name, suff='-', has_arg=False)
    for macro in macros:
        result.add_macro(macro)
    return result

def with_param(name, macros=[]):
    result = CompilerOption(name, suff=None, has_arg=True, separate_arg_with_space=False)
    for macro in macros:
        result.add_macro(macro)
    return result


class CompilerInfo:
    def __init__(self, toolset, executable, id, macros):
        self.__toolset = toolset
        self.__executable = executable
        self.__id = id
        self.__macros = macros

    def toolset(self): return self.__toolset
    def executable(self): return self.__executable
    def id(self): return self.__id
    def macros(self): return self.__macros

class CompilerWrapper(CmdLineOptions):
    def preprocess_option(self): raise NotImplementedError()
    def object_name_option(self): raise NotImplementedError()
    def compile_no_link_option(self): raise NotImplementedError()
    def define_option(self): raise NotImplementedError()
    def include_option(self): raise NotImplementedError()
    def use_pch_option(self): raise NotImplementedError()
    def pch_file_option(self): raise NotImplementedError()

    def __init__(self, esc):
        super(CompilerWrapper, self).__init__(esc)
        self.use_pch_option().add_category(CompilationCategory)
        self.pch_file_option().add_category(PCHCategory)
        self.compile_no_link_option().add_category(CompilationCategory)
        self.include_option().add_category(PreprocessingCategory)
        self.define_option().add_category(PreprocessingCategory)
        self.add_option(self.compile_no_link_option())
        self.add_option(self.object_name_option())
        self.add_option(self.use_pch_option())
        self.add_option(self.pch_file_option())
        self.add_option(self.define_option())
        self.add_option(self.include_option())

    def compiler_info(self, executable):
        raise NotImplementedError("Compiler identification not implemented.")

    def compiler_option_macros(self, option_values):
        result = []
        for option_value in (x for x in option_values
            if type(x.option) == CompilerOption and
            x.option.test_category(PreprocessingCategory)):
            result += token.option.get_macros(token.val)
        return result

    def requires_preprocessing(self, file):
        return False

class MSVCWrapper(CompilerWrapper):
    __preprocess_option = simple('E')
    __object_name_option = with_param('Fo')
    __compile_no_link_option = simple('c')
    __include_option = with_param('I')
    __define_option = with_param('D')
    __use_pch_option = with_param('Yu')
    __pch_file_option = with_param('Fp')

    def preprocess_option(self): return self.__preprocess_option
    def object_name_option(self): return self.__object_name_option
    def compile_no_link_option(self): return self.__compile_no_link_option
    def include_option(self): return self.__include_option
    def define_option(self): return self.__define_option
    def use_pch_option(self): return self.__use_pch_option
    def pch_file_option(self): return self.__pch_file_option

    def __init__(self):
        super(MSVCWrapper, self).__init__(esc = ['/', '-'])

        # Build Local
        for option in self.build_local_options:
            option.add_category(BuildLocalCategory)
            self.add_option(option)
        # Preprocessing
        for option in self.preprocessing_options:
            option.add_category(PreprocessingCategory)
            self.add_option(option)
        # PCH options which require local build.        
        for option in self.pch_build_local_options:
            option.add_category(BuildLocalCategory)
            option.add_category(PCHCategory)
            self.add_option(option)
        # PCH options.
        for option in self.pch_options:
            option.add_category(PCHCategory)
            self.add_option(option)
        # Both preprocessing and compilation.
        for option in self.preprocess_and_compile:
            option.add_category(PreprocessingCategory)
            option.add_category(CompilationCategory)
            self.add_option(option)
        # Compilation
        for option in self.compilation_options:
            option.add_category(CompilationCategory)
            self.add_option(option)
        # Options requiring special handling.
        for option in self.special_handling:
            option.add_category(SpecialHandlingCategory)
            self.add_option(option)
        # Always.
        for option in self.always:
            option.add_category(PreprocessingCategory)
            option.add_category(CompilationCategory)
            option.add_category(LinkingCategory)
            self.add_option(option)

    def requires_preprocessing(self, input):
        # FIXME: This should be handled better.
        # Currently we expect there is no /TC, /TP,
        # /Tc or /Tp options on the command line
        return os.path.splitext(input)[1].lower() in ['.c', '.cpp', '.cxx']

    placeholder_string = '__PLACEHOLDER_G87AD68BGV7AD67BV8ADR8B6'

    class TestSource:
        def __init__(self, executable, macros, placeholder_string):
            self.executable = executable
            cpp_handle, self.cpp_filename = tempfile.mkstemp(suffix='.cpp')
            obj_handle, self.obj_filename = tempfile.mkstemp(suffix='.obj')
            os.close(obj_handle)
            with os.fdopen(cpp_handle, 'wt') as file:
                lines = []
                # For _CPPLIB_VER and _HAS_ITERATOR_DEBUGGING
                lines.append("#include <yvals.h>\n")
                # Stolen from Boost.PP
                lines.append("#define STR(x) STR_I((x))\n")
                lines.append("#define STR_I(x) STR_II x\n")
                lines.append("#define STR_II(x) #x\n")
                for symbol in macros:
                    lines.append('#ifndef {m}\n'.format(m=symbol))
                    lines.append('#pragma message("{plh} /{m}/__NOT_DEFINED__/")\n'.format(plh=placeholder_string, m=symbol))
                    lines.append('#else\n')
                    lines.append('#pragma message("{plh} /{m}/" STR({m}) "/")\n'.format(plh=placeholder_string, m=symbol))
                    lines.append('#endif\n')
                file.writelines(lines)

        def destroy(self):
            os.remove(self.cpp_filename)
            os.remove(self.obj_filename)

        def command(self):
            return [self.executable, '/Fo{}'.format(self.obj_filename), '-c', self.cpp_filename]

    def prepare_test_source(self, executable):
        #   Here we should test only for macros which do not change depending on
        # compiler options, i.e. which are fixed for a specific compiler
        # executable.
        macros = ('_MSC_VER', '_MSC_FULL_VER', '_CPPLIB_VER', '_HAS_TR1',
            '_WIN32', '_WIN64', '_M_IX86', '_M_IA64', '_M_MPPC', '_M_MRX000',
            '_M_PPC', '_M_X64', '_INTEGRAL_MAX_BITS', '__cplusplus')
        return MSVCWrapper.TestSource(executable, macros, self.placeholder_string)

    def compiler_info(self, executable, stdout, stderr):
        output = stdout.split(b'\r\n')
        macros = []
        for line in output:
            m = re.match(('{plh} /(.*)/(.*)/'.format(plh=self.placeholder_string)).encode('ascii'), line)
            if m:
                if m.group(2) == b'__NOT_DEFINED__':
                    continue
                macros.append('{}={}'.format(m.group(1).decode(), m.group(2).decode()))
        m = re.search(b'C/C\+\+ Optimizing Compiler Version (?P<ver>.*) for (?P<plat>.*)\r\n', stderr)
        if not m:
            raise EnvironmentError("Failed to identify compiler - unexpected output.")
        version = (m.group('ver'), m.group('plat'))
        assert version in self.compiler_versions
        result = CompilerInfo("msvc", os.path.split(executable)[1], version, macros)
        result.pch_file_option = self.pch_file_option()
        result.define_option = self.define_option()
        result.include_option = self.include_option()
        result.object_name_option = self.object_name_option()
        result.compile_no_link_option = self.compile_no_link_option()
        return result

    def compiler_option_macros(self, tokens):
        result = []
        add_extensions = True
        for token in (token for token in tokens
            if type(token.option) == CompilerOption and
            token.option.test_category(PreprocessingCategory)):
            option = token.option
            if not option:
                continue
            if option.name() == 'Za':
                add_extensions = False
            if option.name() == 'Ze':
                add_extensions = True
            result += token.option.get_macros(token.val)
        if add_extensions:
            result.append('_MSC_EXTENSIONS=1')
        return result

    def create_call(self, option_values):
        compile_call = ['cl.exe']
        compile_call.extend(option.make_str() for option in
            option_values.filter_options(CompilationCategory))
        macros = [token.val for token in option_values.filter_options(self.define_option())]
        compile_call.extend(self.define_option().make_value(define).make_str() for define in macros)
        # Disable generating PDB files when compiling cpp into obj.
        # Store debug info in the obj file itself.
        if option_values.filter_options('Zi'):
            compile_call.append('/Z7')
        return compile_call, self.compiler_option_macros(option_values.all())

    @classmethod
    def get_compiler_environment(cls, compiler_info):
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
        return get_batch_file_environment_side_effects(script, [info[1]])

    @classmethod
    def setup_compiler(cls, compiler_info):
        def run_compiler(command, cwd, compiler_environ):
            env = dict(os.environ)
            env.update(compiler_environ)
            with subprocess.Popen(command, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True) as proc:
                output = proc.communicate()
                return proc.returncode, output[0], output[1]
        compiler_env = MSVCWrapper.get_compiler_environment(compiler_info)
        if compiler_env:
            return lambda command, cwd : run_compiler(command, cwd, compiler_env)
        return None

    compiler_versions = {
        (b'15.00.30729.01', b'80x86') : (9 , 'x86'  ), # msvc9
        (b'15.00.30729.01', b'x64'  ) : (9 , 'amd64'), # msvc9 x64
        (b'16.00.40219.01', b'80x86') : (10, 'x86'  ), # msvc10
        (b'16.00.40219.01', b'x64'  ) : (10, 'amd64'), # msvc10 x64
        (b'17.00.50727.1' , b'x86'  ) : (11, 'x86'  ), # msvc11
        (b'17.00.50727.1' , b'x64'  ) : (11, 'amd64'), # msvc11 x64
    }

    build_local_options = [
        # If we run into these just run the damn thing locally
        simple('E' ), simple('EP'), simple('P' ),
        simple('Zg'), simple('Zs')]

    preprocessing_options = [
        with_param('AI'), with_param('FU'), with_param('D' ), with_param('FI'),
        with_param('U' ), with_param('I' ), simple    ('C' ), simple    ('Fx'),
        simple    ('u' ), simple    ('X' )]

    pch_build_local_options = [
        # If we are creating PCH file compile it locally. For now.
        with_param('Yc')]

    pch_options = [
        with_param('Fp'), with_param('Yl'), simple('Y-')]

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

    special_handling = [
        simple      ('Zi'),
        with_param  ('Fd')]

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
        with_param    ('Fe'), with_param    ('Fm'), with_param    ('Fr'), with_param  ('FR'),
        with_param   ('doc'), simple        ('Zi'), simple      ('Z7'),
        with_param    ('Zp'), with_param    ('vd'), with_param    ('vm'), 
        simple        ('?'),  simple      ('help'), simple    ('bigobj'), with_param  ('errorReport'),
        simple        ('FC'), with_param    ('H') , simple         ('J'), with_param  ('MP'),
        simple        ('showIncludes')            , with_param    ('Tc'), with_param  ('Tp'),
        simple        ('TC'), simple        ('TP'), with_param     ('V'), simple      ('w'),
        with_param    ('wd'), with_param    ('we'), with_param    ('wo'), with_param  ('w'),
        simple      ('Wall'), simple        ('WL'), simple        ('WX'), with_param  ('W'),
        simple        ('Yd'), with_param    ('Zm'), simple        ('LD'), simple      ('LN'),
        with_param     ('F'), simple      ('link'), with_param('analyze')]
