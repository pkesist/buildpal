import os
import sys
from distribute_call import CompilationDistributer, CmdLineOption, FreeOption

class MSVCDistributer(CompilationDistributer):
    def __init__(self):
        super().__init__(preprocess_option=MSVCDistributer.CompilerOption('E', self.esc, False),
            obj_name_option=MSVCDistributer.CompilerOption('Fo', self.esc, None, True, False, False),
            compile_no_link_option=MSVCDistributer.CompilerOption('c', self.esc, None, False))
        for option_desc in self.preprocessing_options:
            self.add_preprocessing_option(*option_desc)
        for option_desc in self.compilation_options:
            self.add_compilation_option(*option_desc)
        for option_desc in self.pch_options:
            # Recognized, but ignored.
            self.add_option(MSVCDistributer.CompilerOption(*option_desc))
        for option_desc in self.preprocess_and_compile:
            option=MSVCDistributer.CompilerOption(*option_desc)
            option.add_category(CompilationDistributer.PreprocessingCategory)
            option.add_category(CompilationDistributer.CompilationCategory)
            self.add_option(option)

    def requires_preprocessing(self, input):
        # This should be handled better.
        # Currently we expect there is no /TC, /TP,
        # /Tc or /Tp options on the command line
        return os.path.splitext(input)[1].lower() in ['.c', '.cpp', '.cxx']

    def should_invoke_linker(self, ctx):
        for value in ctx.options():
            if value.option.name() in ['c', 'E', 'EP', 'P', 'Zg', 'Zs']:
                return False
        return True

    esc = ['/', '-']
    preprocessing_options = [
        ['AI', esc, None, True , False, False],
        ['FU', esc, None, True , False, False],
        ['C' , esc, None, False              ],
        ['D' , esc, None, True , False, False],
        #['E', esc, None, False              ],
        ['EP', esc, None, False              ],
        ['P' , esc, None, False              ],
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
        # Preprocessor can determine whether exceptions are enabled
        # or not.
        ['EH', esc, None, True, False, False ],
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
        #['Fo'                   , esc, None, True , False, False],
        ['Fr'                   , esc, None, True , False, False],
        ['FR'                   , esc, None, True , False, False],
        ['doc'                  , esc, None, True , False, False],
        ['Zi'                   , esc, None, False              ],
        ['Z7'                   , esc, None, False              ],
        ['Zp'                   , esc, None, True , False, False],
        ['Za'                   , esc, None, False              ],
        ['Ze'                   , esc, None, False              ],
        ['Zl'                   , esc, None, False              ],
        ['Zg'                   , esc, None, False              ],
        ['Zs'                   , esc, None, False              ],
        ['vd'                   , esc, None, True , False, False],
        ['vm'                   , esc, None, True , False, False],
        ['Zc'                   , esc, None, True , False, False],
        ['ZI'                   , esc, None, False              ],
        ['openmp'               , esc, None, False              ],
        ['?'                    , esc, None, False              ],
        ['help'                 , esc, None, False              ],
        ['bigobj'               , esc, None, False              ],
        #['c'                   , esc, None, False              ],
        ['errorReport'          , esc, None, True , False, False],
        ['FC'                   , esc, None, False              ],
        ['H'                    , esc, None, True , False, False],
        ['J'                    , esc, None, False              ],
        ['MP'                   , esc, None, True , False, False],
        ['nologo'               , esc, None, False              ],
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
        ['MD'                   , esc, None, False              ],
        ['MT'                   , esc, None, False              ],
        ['MDd'                  , esc, None, False              ],
        ['MTd'                  , esc, None, False              ],
        ['analyze'              , esc, None, True , False, False]
    ]

if __name__ == "__main__":
    distributer = MSVCDistributer()
    distributer.execute(sys.argv[1:])
