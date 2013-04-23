from ply.lex import lex
from ply.cpp import *

class ResolveInclude(Preprocessor):
    def __init__(self, callback, lexer):
        super(ResolveInclude, self).__init__(lexer)
        self.__callback = callback
        self.__include_stack = []
        self.__cached_includes = {}
        self.source = None

    class Include:
        def __init__(self, stack):
            self.__stack = stack

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.__stack.pop()

    def start_include(self, source):
        result = self.Include(self.__include_stack)
        self.__include_stack.append(source)
        return result

    def error(self,file,line,msg):
        raise RuntimeError("%s:%d %s" % (file,line,msg))

    def include(self, tokens):
        # Try to extract the filename and then process an include file
        with self.start_include(self.source):
            if not tokens:
                return
            macros = {}
            if tokens[0].value != '<' and tokens[0].type != self.t_STRING:
                def notify(macro, value):
                    macros[macro] = value
                expanded = self.expand_macros(tokens, notify=notify)
                if macros:
                    self.__callback(self.source, 'HAS_MACRO_INCLUDE', (self.__include_stack, macros))
            else:
                expanded = tokens

            if expanded[0].value == '<':
                # Include <...>
                i = 1
                while i < len(expanded):
                    if expanded[i].value == '>':
                        break
                    i += 1
                else:
                    self.error(self.source, expanded[i].lineno, "Malformed #include <...>")
                    return
                filename = "".join([x.value for x in expanded[1:i]])
                path = self.path + [""] + self.temp_path
            elif expanded[0].type == self.t_STRING:
                filename = expanded[0].value[1:-1]
                path = self.temp_path + [""] + self.path
            else:
                self.error(self.source, expanded[0].lineno, "Malformed #include statement '{}'".format(expanded[0].value))
                return

            # True if already known
            if self.__callback(filename, 'IS_CACHED', (self.__include_stack, macros)):
                print("Using '{}' data from cache.".format(filename))
                return
            for p in path:
                iname = os.path.normpath(os.path.join(p, filename))
                if os.path.isfile(iname):
                    self.__callback(filename, 'FOUND', iname)
                    dname = os.path.dirname(iname)
                    if dname:
                        self.temp_path.insert(0,dname)
                    self.preprocess_file(iname)
                    if dname:
                        del self.temp_path[0]
                    break
            else:
                self.__callback(filename, 'NOT_FOUND')

    def preprocess(self, preprocessor_commands):
        enable = True
        iftrigger = False
        for line, name, args in preprocessor_commands:
            #print("{}:{} - {} - {}".format(self.source, line, name + "".join(a.value for a in args), "Enable" if enable else "Disable"))
            if name == 'define':
                if enable:
                    self.define(args)
            elif name == 'include':
                if enable:
                    oldfile = self.macros['__FILE__']
                    self.include(args)
                    self.macros['__FILE__'] = oldfile
            elif name == 'undef':
                if enable:
                    self.undef(args)
            elif name == 'ifdef':
                self.ifstack.append((enable, iftrigger))
                if enable:
                    if not args[0].value in self.macros:
                        enable = False
                        iftrigger = False
                    else:
                        iftrigger = True
            elif name == 'ifndef':
                self.ifstack.append((enable, iftrigger))
                if enable:
                    if args[0].value in self.macros:
                        enable = False
                        iftrigger = False
                    else:
                        iftrigger = True
            elif name == 'if':
                self.ifstack.append((enable, iftrigger))
                if enable:
                    result = self.evalexpr(args)
                    if not result:
                        enable = False
                        iftrigger = False
                    else:
                        iftrigger = True
            elif name == 'elif':
                if self.ifstack:
                    if self.ifstack[-1][0]:     # We only pay attention if outer "if" allows this
                        if enable:         # If already true, we flip enable False
                            enable = False
                        elif not iftrigger:   # If False, but not triggered yet, we'll check expression
                            result = self.evalexpr(args)
                            if result:
                                enable  = True
                                iftrigger = True
                else:
                    self.error(self.source,dirtokens[0].lineno,"Misplaced #elif")
                        
            elif name == 'else':
                if self.ifstack:
                    if self.ifstack[-1][0]:
                        if enable:
                            enable = False
                        elif not iftrigger:
                            enable = True
                            iftrigger = True
                else:
                    self.error(self.source,dirtokens[0].lineno,"Misplaced #else")

            elif name == 'endif':
                if self.ifstack:
                    enable, iftrigger = self.ifstack.pop()
                else:
                    self.error(self.source,dirtokens[0].lineno,"Misplaced #endif")

            elif name == 'pragma' and args[0].value == 'debug':
                if True:
                    if len(args)>1:
                        i = 1
                        while i < len(args):
                            if args[i].type == 'CPP_ID':
                                macro = args[i].value
                                if macro in self.macros:
                                    print('MACRO - {} - {} - {}'.format(macro, "".join(x.value for x in self.macros[macro].value), "Enabled" if enable else "Disable"))
                                else:
                                    print("MACRO '{}' not defined - {}".format(macro, "Enabled" if enable else "Disable"))
                            i += 1
                    else:
                        for macro in self.macros:
                            print('MACRO - {} - {}'.format(macro, "".join(x.value for x in self.macros[macro].value), "Enabled" if enable else "Disable"))

            else:
                # Unknown preprocessor directive
                pass


    def preprocess_file(self, filename):
        if filename not in self.__cached_includes:
            self.__cached_includes[filename] = []
            input = open(filename, "r").read()
            # Replace trigraph sequences
            t = trigraph(input)
            lines = self.group_lines(t)
            for x in lines:
                for i,tok in enumerate(x):
                    if tok.type not in self.t_WS: break
                if tok.value == '#':
                    # Preprocessor directive
                    dirtokens = self.tokenstrip(x[i+1:])
                    if not dirtokens:
                        continue

                    self.__cached_includes[filename].append((dirtokens[0].lineno, dirtokens[0].value, self.tokenstrip(dirtokens[1:])))
        
        oldfile = self.source
        self.source = filename
        self.preprocess(self.__cached_includes[filename])
        self.source = oldfile

    def start(self, file):
        self.source = file
        self.macros['__FILE__'] = file
        self.ifstack = []
        self.preprocess_file(file)

def get_all_headers(file, search_path, defines):
    result = {}
    def found_include(name, what, param = None):
        name = os.path.normpath(name)
        if what == 'HAS_MACRO_INCLUDE':
            pass
        elif what == 'IS_CACHED':
            return False
        elif what == 'FOUND':
            result[name] = param
        elif what == 'NOT_FOUND':
            result[name] = None
        else:
            raise RuntimeError("Invalid callback verb '{}'.".format(what))

    lexer = lex()
    p = ResolveInclude(found_include, lexer)
    p.temp_path.append(os.path.split(file)[0])
    for path in search_path:
        p.add_path(path)
    for define in defines:
        p.define(define.replace('=', ' '))
    p.start(file)
    return result


if __name__ == '__main__':
    import ply.lex as lex
    lexer = lex.lex()

    # Run a preprocessor
    import sys
    f = open(sys.argv[1])
    input = f.read()

    p = Preprocessor(lexer)
    p.parse(input,sys.argv[1])
    while True:
        tok = p.token()
        if not tok: break
        print(p.source, tok)
    for macro in p.macros:
        print(macro, [x.value for x in p.macros[macro].value])
