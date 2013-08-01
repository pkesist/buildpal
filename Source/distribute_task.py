

class CompileTask:
    def __init__(self, cwd, call, source, source_type, preprocessor_info, output, compiler_info, pch_file, pch_header, compilerWrapper):
        self.call = call
        self.source_type = source_type
        self.compiler_info = compiler_info
        self.output_switch = compilerWrapper.object_name_option().make_value('{}').make_str()
        self.compile_switch = compilerWrapper.compile_no_link_option().make_value().make_str()
        self.cwd = cwd
        self.preprocessor_info = preprocessor_info
        self.pch_file = pch_file
        self.pch_header = pch_header
        self.output = output
        self.source = source
        self.tempfile = None

        self.algorithm = 'SCAN_HEADERS'
        #self.algorithm = 'PREPROCESS_LOCALLY'
