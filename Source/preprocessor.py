from ply.lex import lex
from ply.cpp import *

class ResolveInclude(Preprocessor):
    def __init__(self, callback, lexer):
        super(ResolveInclude, self).__init__(lexer)
        self.__callback = callback

    def error(self,file,line,msg):
        raise RuntimeError("%s:%d %s" % (file,line,msg))

    def include(self, tokens, ifstack):
        # Try to extract the filename and then process an include file
        if not tokens:
            return
        if tokens:
            if tokens[0].value != '<' and tokens[0].type != self.t_STRING:
                tokens = self.expand_macros(tokens)

            if tokens[0].value == '<':
                # Include <...>
                i = 1
                while i < len(tokens):
                    if tokens[i].value == '>':
                        break
                    i += 1
                else:
                    self.error(self.source, tokens[i].lineno, "Malformed #include <...>")
                    return
                filename = "".join([x.value for x in tokens[1:i]])
                path = self.path + [""] + self.temp_path
            elif tokens[0].type == self.t_STRING:
                filename = tokens[0].value[1:-1]
                path = self.temp_path + [""] + self.path
            else:
                self.error(self.source, tokens[0].lineno,"Malformed #include statement '{}'".format(tokens[0].value))
                return
        for p in path:
            iname = os.path.join(p,filename)
            try:
                data = open(iname,"r").read()
                self.__callback(filename, iname)
                dname = os.path.dirname(iname)
                if dname:
                    self.temp_path.insert(0,dname)
                #for tok in self.parsegen(data,filename, ifstack):
                #    yield tok
                self.parsegen(data, filename, ifstack)
                if dname:
                    del self.temp_path[0]
                break
            except IOError as e:
                pass
        else:
            self.__callback(filename, None)

    def parsegen(self, input, source=None, ifstack=[]):
        # Replace trigraph sequences
        t = trigraph(input)
        lines = self.group_lines(t)

        if not source:
            source = ""
            
        self.define("__FILE__ \"%s\"" % source)

        self.source = source
        chunk = []
        enable = True
        iftrigger = False

        for x in lines:
            for i,tok in enumerate(x):
                if tok.type not in self.t_WS: break
            if tok.value == '#':
                # Preprocessor directive
                for tok in x:
                    if tok in self.t_WS and '\n' in tok.value:
                        chunk.append(tok)
                
                dirtokens = self.tokenstrip(x[i+1:])
                if dirtokens:
                    name = dirtokens[0].value
                    args = self.tokenstrip(dirtokens[1:])
                else:
                    name = ""
                    args = []

                if name == 'define':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            pass #yield tok
                        chunk = []
                        self.define(args)
                elif name == 'include':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            pass #yield tok
                        chunk = []
                        oldfile = self.macros['__FILE__']
                        #for tok in self.include(args, ifstack):
                        #    yield tok
                        self.include(args, ifstack)
                        self.macros['__FILE__'] = oldfile
                        self.source = source
                elif name == 'undef':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            pass #yield tok
                        chunk = []
                        self.undef(args)
                elif name == 'ifdef':
                    ifstack.append((enable,iftrigger))
                    if enable:
                        if not args[0].value in self.macros:
                            enable = False
                            iftrigger = False
                        else:
                            iftrigger = True
                elif name == 'ifndef':
                    ifstack.append((enable,iftrigger))
                    if enable:
                        if args[0].value in self.macros:
                            enable = False
                            iftrigger = False
                        else:
                            iftrigger = True
                elif name == 'if':
                    ifstack.append((enable,iftrigger))
                    if enable:
                        result = self.evalexpr(args)
                        if not result:
                            enable = False
                            iftrigger = False
                        else:
                            iftrigger = True
                elif name == 'elif':
                    if ifstack:
                        if ifstack[-1][0]:     # We only pay attention if outer "if" allows this
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
                    if ifstack:
                        if ifstack[-1][0]:
                            if enable:
                                enable = False
                            elif not iftrigger:
                                enable = True
                                iftrigger = True
                    else:
                        self.error(self.source,dirtokens[0].lineno,"Misplaced #else")

                elif name == 'endif':
                    if ifstack:
                        enable,iftrigger = ifstack.pop()
                    else:
                        self.error(self.source,dirtokens[0].lineno,"Misplaced #endif")

                elif name == 'pragma' and args[0].value == 'debug':
                    if enable:
                        if len(args)>1:
                            i = 1
                            while i < len(args):
                                if args[i].type != 'CPP_ID':
                                    i += 1
                                    continue
                                macro = args[i].value
                                if macro in self.macros:
                                    print('MACRO - {} - {}'.format(macro, "".join(x.value for x in self.macros[macro].value)))
                                else:
                                    print("MACRO '{}' not defined".format(macro))
                                i += 1
                        else:
                            for macro in self.macros:
                                print('MACRO - {} - {}'.format(macro, "".join(x.value for x in self.macros[macro].value)))

                else:
                    # Unknown preprocessor directive
                    pass

        for tok in self.expand_macros(chunk):
            pass #yield tok
        chunk = []
        
def get_all_headers(file, search_path, defines):
    result = {}

    def found_include(name, file):
        #print("Found '{}' as '{}'.".format(name, file))
        result[name] = file

    f = open(file)
    input = f.read()

    lexer = lex()
    p = ResolveInclude(found_include, lexer)
    p.temp_path.append(os.path.split(file)[0])
    for path in search_path:
        p.add_path(path)
    for define in defines:
        p.define(define.replace('=', ' '))
    p.parse(input, file)
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
