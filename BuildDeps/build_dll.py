from distutils.command.build_clib import build_clib
from distutils.ccompiler import new_compiler
from distutils.dep_util import newer

import os

class build_dll(build_clib):
    def initialize_options(self):
        super().initialize_options()
        self.compile_args = []
        self.link_args = []
        self.link_libs = []
        self.plat = None

    def finalize_options(self):
        self.set_undefined_options('build',
                            ('build_lib', 'build_clib'))
        return super().finalize_options()

    def run(self):
        assert self.libraries
        self.build_libraries(self.libraries)

    def prepare_compiler(self, plat):
        compiler = new_compiler(compiler=self.compiler,
            dry_run=self.dry_run,
            force=self.force)
        compiler.initialize(plat)

        if self.include_dirs is not None:
            compiler.set_include_dirs(self.include_dirs)
        if self.define is not None:
            # 'define' option is a list of (name,value) tuples
            for (name,value) in self.define:
                compiler.define_macro(name, value)
        if self.undef is not None:
            for macro in self.undef:
                compiler.undefine_macro(macro)
        return compiler

    def build_libraries(self, libraries):
        for (lib_name, build_info) in libraries:
            compiler = self.prepare_compiler(build_info.get('plat'))
            sources = build_info.get('sources')
            if sources is None or not isinstance(sources, (list, tuple)):
                raise DistutilsSetupError(
                       "in 'libraries' option (library '%s'), "
                       "'sources' must be present and must be "
                       "a list of source filenames" % lib_name)
            sources = list(sources)
            target = os.path.join(self.build_clib, lib_name + ".dll")
            if not any([newer(source, target) for source in sources]):
                continue

            macros = build_info.get('macros')
            include_dirs = build_info.get('include_dirs')
            objects = compiler.compile(sources,
                output_dir=self.build_temp,
                macros=macros,
                include_dirs=include_dirs,
                debug=self.debug,
                extra_postargs=self.compile_args)

            link_args = self.link_args
            link_args.append('/DEF:{}'.format(build_info['def_file']))
            compiler.link_shared_lib(objects, lib_name,
                output_dir=self.build_clib,
                debug=self.debug,
                libraries=self.link_libs,
                extra_postargs=self.link_args)

