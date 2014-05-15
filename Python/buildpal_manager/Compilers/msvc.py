import parse_args

from .utils import get_batch_file_environment_side_effects

import itertools
import os
import re
import sys
import tempfile

class CompileOptions:
    def __init__(self, compiler_wrapper, options):
        self.compiler = compiler_wrapper
        arg_list = parse_args.ArgList(options)
        self.option_names = arg_list.option_names()
        self.option_values = arg_list.option_values()
        self.arg_values = arg_list.arg_values()
        self.value_dict = {}
        self.arg_dict = {}
        for x, y in zip(self.option_names, self.option_values):
            self.value_dict.setdefault(x, []).append(y)
        for x, y in zip(self.option_names, self.arg_values):
            self.arg_dict.setdefault(x, []).append(y)

    def implicit_macros(self):
        macros = []
        add_extensions = True
        for option_name, opt_value in zip(self.option_names, self.option_values):
            if option_name == 'Za':
                add_extensions = False
            if option_name == 'Ze':
                add_extensions = True
            if option_name in self.compiler.implicit_macros():
                macros.extend(self.compiler.implicit_macros()[option_name])
        if add_extensions:
            macros.append('_MSC_EXTENSIONS=1')
        return macros

    def should_build_locally(self):
        return any((x in self.compiler.build_local_options() for x in self.value_dict))

    def should_invoke_linker(self):
        return self.value_dict.get(self.compiler.compile_no_link_option()) is None

    def pch_header(self):
        opt = self.value_dict.get(self.compiler.use_pch_option())
        if not opt:
            return None
        assert len(opt[-1]) == 1
        return opt[-1][0]

    def pch_file(self):
        opt = self.value_dict.get(self.compiler.pch_file_option())
        if not opt:
            return None
        assert len(opt[-1]) == 1
        return opt[-1][0]

    def includes(self):
        return list(itertools.chain(*self.value_dict.get(self.compiler.include_option(), [])))

    def defines(self):
        return list(itertools.chain(*self.value_dict.get(self.compiler.define_option(), [])))

    def create_server_call(self):
        result = ['/c']
        exclude_opts = ['c', 'I', 'Fo', 'link', '<input>', 'Fp', 'Yc']
        for name, value in zip(self.option_names, self.arg_values):
            if name == 'Zi':
                # Disable generating PDB files when compiling cpp into obj.
                # Store debug info in the obj file itself.
                result.append('/Z7')
            elif name not in exclude_opts:
                result.extend(value)
        return result

    def input_files(self):
        return list(x for x in itertools.chain(*self.value_dict.get('<input>')) if x != '/FD')

    def output_file(self):
        result = self.value_dict.get(self.compiler.object_name_option())
        if not result:
            return None
        assert len(result[-1]) == 1
        return result[-1][0]

    def files(self):
        sources = self.input_files()
        output = self.output_file()
        if output:
            if output[-1] == os.path.sep or output[-1] == os.path.altsep:
                outputs = [os.path.join(output, os.path.splitext(
                    os.path.basename(src))[0] + '.obj') for src in sources]
                return zip(sources, outputs)
            else:
                if len(sources) > 1:
                    raise RuntimeError("Cannot specify output file " \
                        "with multiple sources.")
                return [(sources[0], output)]
        return [(src, os.path.splitext(os.path.basename(src))[0] + '.obj')
            for src in sources]

    def link_options(self):
        return self.arg_dict.get(self.compiler.link_option())

class MSVCCompiler:
    @classmethod
    def object_name_option(cls): return 'Fo'

    @classmethod
    def set_object_name_option(cls): return '/Fo{}'

    @classmethod
    def compile_no_link_option(cls): return 'c'

    @classmethod
    def include_option(cls): return 'I'

    @classmethod
    def set_include_option(cls): return '/I{}'

    @classmethod
    def define_option(cls): return 'D'

    @classmethod
    def set_define_option(cls): return '/D{}'

    @classmethod
    def use_pch_option(cls): return 'Yu'

    @classmethod
    def pch_file_option(cls): return 'Fp'

    @classmethod
    def set_pch_file_option(cls): return '/Fp{}'

    @classmethod
    def build_local_options(cls): 
        return ['E', 'EP', 'P', 'Zg', 'Zs', 'Yc']

    @classmethod
    def preprocessing_options(cls):
        return ['AI', 'FU', 'D', 'FI', 'U' , 'I' , 'C', 'Fx', 'u' , 'X']

    @classmethod
    def link_option(cls):
        return 'link'

    @classmethod
    def implicit_macros(cls):
        return {
        'EH'        : ['_CPPUNWIND'],
        'MD'        : ['_MT', '_DLL'],
        'MT'        : ['_MT'],
        'MDd'       : ['_MT', '_DLL', '_DEBUG'],
        'MTd'       : ['_MT', '_DEBUG'],
        'GR'        : ['_CPPRTTI'],
        'GX'        : ['_CPPUNWIND'],
        'RTC'       : ['__MSVC_RUNTIME_CHECKS'],
        'clr'       : ['__cplusplus_cli=200406'],
        'Zl'        : ['_VC_NODEFAULTLIB'],
        'Zc:whar_t' : ['_NATIVE_WCHAR_T_DEFINED'],
        'openmp'    : ['_OPENMP'],
        'Wp64'      : ['_Wp64'],
        'LDd'       : ['_DEBUG'],
    }

    @classmethod
    def parse_options(cls, options):
        return CompileOptions(cls, options)

    placeholder_string = '__PLACEHOLDER_G87AD68BGV7AD67BV8ADR8B6'

    class TestSource:
        def __init__(self, macros, placeholder_string):
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
                    lines.append('#pragma message("{plh}/{m}/__NOT_DEFINED__/")\n'.format(plh=placeholder_string, m=symbol))
                    lines.append('#else\n')
                    lines.append('#pragma message("{plh}/{m}/" STR({m}) "/")\n'.format(plh=placeholder_string, m=symbol))
                    lines.append('#endif\n')
                file.writelines(lines)

        def destroy(self):
            os.remove(self.cpp_filename)
            os.remove(self.obj_filename)

        def command(self):
            return ['/Fo{}'.format(self.obj_filename), '-c', self.cpp_filename]

    def prepare_test_source(self):
        #   Here we should test only for macros which do not change depending on
        # compiler options, i.e. which are fixed for a specific compiler
        # executable.
        macros = ('_MSC_VER', '_MSC_FULL_VER', '_CPPLIB_VER', '_HAS_TR1',
            '_WIN32', '_WIN64', '_M_IX86', '_M_IA64', '_M_MPPC', '_M_MRX000',
            '_M_PPC', '_M_X64', '_M_ARM', '_INTEGRAL_MAX_BITS', '__cplusplus')
        return MSVCCompiler.TestSource(macros, self.placeholder_string)

    def get_compiler_info(self, executable, stdout, stderr):
        output = stdout.split(b'\r\n')
        macros = []
        for line in output:
            m = re.match(('{plh}/(.*)/(.*)/'.format(plh=self.placeholder_string)).encode('ascii'), line)
            if m:
                if m.group(2) == b'__NOT_DEFINED__':
                    continue
                macros.append('{}={}'.format(m.group(1).decode(), m.group(2).decode()))
        m = re.search(b'C/C\+\+ Optimizing Compiler Version (?P<ver>.*) for (?P<plat>.*)\r\n', stderr)
        if not m:
            raise EnvironmentError("Failed to identify compiler - unexpected output.")
        version = (m.group('ver'), m.group('plat'))
        return dict(
            executable = os.path.basename(executable),
            id = version,
            macros = macros,
            set_object_name = self.set_object_name_option(),
            set_pch_file = self.set_pch_file_option(),
            set_include_option = self.set_include_option(),
        ), self.compiler_files[version[0][:5]]


    compiler_files = {
        b'15.00' : 
        [
            b'c1.dll',
            b'c1ast.dll',
            b'c1xx.dll',
            b'c1xxast.dll',
            b'c2.dll',
            b'cl.exe',
            b'mspdb80.dll',
            b'1033/atlprovui.dll',
            b'1033/bscmakeui.dll',
            b'1033/clui.dll',
            b'1033/cvtresui.dll',
            b'1033/linkui.dll',
            b'1033/mspft80ui.dll',
            b'1033/nmakeui.dll',
            b'1033/pgort90ui.dll',
            b'1033/pgoui.dll',
            b'1033/vcomp90ui.dll'],
        b'16.00' :
        [
            b'c1.dll',
            b'c1xx.dll',
            b'c2.dll',
            b'cl.exe',
            b'mspdb100.dll',
            b'1033/atlprovui.dll',
            b'1033/bscmakeui.dll',
            b'1033/clui.dll',
            b'1033/cvtresui.dll',
            b'1033/linkui.dll',
            b'1033/nmakeui.dll',
            b'1033/pgort100ui.dll',
            b'1033/pgoui.dll',
            b'1033/vcomp100ui.dll'],
        b'17.00' :
        [
            b'c1.dll',
            b'c1ast.dll',
            b'c1xx.dll',
            b'c1xxast.dll',
            b'c2.dll',
            b'cl.exe',
            b'mspdb110.dll',
            b'1033/atlprovui.dll',
            b'1033/bscmakeui.dll',
            b'1033/clui.dll',
            b'1033/cvtresui.dll',
            b'1033/linkui.dll',
            b'1033/mspft110ui.dll',
            b'1033/nmakeui.dll',
            b'1033/pgort110ui.dll',
            b'1033/pgoui.dll',
            b'1033/vcomp110ui.dll'],
       }
