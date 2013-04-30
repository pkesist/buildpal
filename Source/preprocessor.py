# #define BBB() 15
# #define BB() 10
# #define B() 5
# 
# #define AAA(x) B##x aaa #x
# 
# #define CCC AAA(B())
# CCC
# 
# #define DDD(x) AAA(B ## x) ddd #x
# DDD(B())
# 
# #define EEE(x) AAA(x) eee #x
# EEE(B())
# 
# 
# #define BOOST_PP_ITERATION_DEPTH() 0
# #define BOOST_PP_INC(x) BOOST_PP_INC_I(x)
# #define BOOST_PP_INC_I(x) BOOST_PP_INC_ ## x
# #define BOOST_PP_CAT(x, y) BOOST_PP_CAT_I(x, y)
# #define BOOST_PP_CAT_I(x, y) x ## y
# 
# 
# 0  : BOOST_PP_CAT(BOOST_PP_ITERATE_, BOOST_PP_INC(BOOST_PP_ITERATION_DEPTH()))
# 1.0: BOOST_PP_CAT_I(BOOST_PP_ITERATE_, BOOST_PP_INC(BOOST_PP_ITERATION_DEPTH()))
# 1.1: BOOST_PP_CAT_I(BOOST_PP_ITERATE_, BOOST_PP_INC_I(BOOST_PP_ITERATION_DEPTH()))
# 1.2: BOOST_PP_CAT_I(BOOST_PP_ITERATE_, BOOST_PP_INC_I(0))
# 1.3: BOOST_PP_CAT_I(BOOST_PP_ITERATE_, 1)
# 2  : BOOST_PP_ITERATE_ ## 1

import itertools
import re

class Token:
    def __init__(self, type, value):
        self.type = type
        self.value = value
    
    def __str__(self):
        return "<Token object: {} - '{}'>".format(self.type, self.value)

    def __repr__(self):
        return "<Token object: {} - '{}'>".format(self.type, self.value)

scanner = re.Scanner([
    (r"[a-zA-Z_]\w*"        , lambda scanner, value: Token('IDENTIFIER', value)),
    (r"\"(?:[^\"\\]|\\.)*\"", lambda scanner, value: Token('STRING'    , value)),
    (r"[0-9]+"              , lambda scanner, value: Token('DIGITS'    , value)),
    (r"[\(\)]"              , lambda scanner, value: Token('BRACKET'   , value)),
    (r"\s+"                 , lambda scanner, value: Token('WHITESPACE', value)),
    (r","                   , lambda scanner, value: Token('COMMA'     , value)),
    (r"##"                  , lambda scanner, value: Token('HASHHASH'  , value)),
    (r"#"                   , lambda scanner, value: Token('HASH'      , value)),
    (r"."                   , lambda scanner, value: Token('OTHER'     , value)),
])

def tokenize(expr):
    result, remainder = scanner.scan(expr)
    if remainder:
        raise Exception("Got unexpected remainder '{}'.".format(remainder))
    return result


class Macro:
    def __init__(self, params, expr):
        self.params = params
        self.expr = tokenize(expr.replace("\\\n", '').strip())
        self.expand = []
        self.stringize = []
        self.cat = []
        last = None
        skip_expand = False
        last_was_cat = False
        last_was_str = False
        i = 0
        while i < len(self.expr):
            token = self.expr[i]
            if token.type not in ['WHITESPACE', 'HASH', 'HASHHASH']:
                if last_was_str:
                    if token.type == 'IDENTIFIER' and token.value not in self.params:
                        del self.expr[last_was_str]
                        i -= 1
                        self.stringize.append(i)
                if last_was_cat:
                    del self.expr[last_was_cat]
                    i -= 1
                    skip_expand = True
                    self.cat.append((last, i))
                last_was_str = None
                last_was_cat = None
                last = i

            if token.type == 'IDENTIFIER':
                if self.params and token.value in self.params and not skip_expand:
                    self.expand.append(i)
                skip_expand = False

            if token.type == 'HASH':
                last_was_str = i

            if token.type == 'HASHHASH':
                last_was_cat = i
                if self.expand and self.expand[-1] == last:
                    del self.expand[-1]
            i += 1
        self.cat.reverse()

    def subst(self, macros, args, depth):
        if len(args) != len(self.params):
            raise Exception("Invalid number of parameters. Expected {}, got {}".format(len(self.params), len(args)))
        result = []
        for i in range(len(self.expr)):
            token = self.expr[i]
            if token.type == 'IDENTIFIER' and token.value in self.params:
                to_add = args[self.params.index(token.value)]
                if i in self.expand:
                    to_add = expand_tokens(macros, to_add, depth)
                result.append(to_add)
            elif token.type == 'WHITESPACE':
                token.value = ' '
                result.append([token])
            else:
                result.append([token])
        assert len(result) == len(self.expr)

        for i in self.stringize:
            assert len(result[i] == 1)
            result[i][0] = '"{}"'.format(result[i][0])
        for a, b in self.cat:
            print(a, b)
            assert a < b
            assert len(result[a]) == 1
            assert len(result[b]) == 1
            result[a] = [result[a][0], result[b][0]]
            del result[a+1:b+1]
        return itertools.chain(*result)
                
def collect_args(tokens):
    i = 0
    while i < len(tokens) and tokens[i].type == 'WHITESPACE':
        i += 1

    if i == len(tokens) or tokens[i].value != '(':
        return None, 0
    nesting = 0
    args = []
    current_arg = []
    
    def trim_arg(what):
        while what and what[0].type == 'WHITESPACE':
            del what[0]
        while what and what[-1].type == 'WHITESPACE':
            del what[-1]
        return what
    while True:
        assert i < len(tokens)
        tok = tokens[i]
        if tok.value == '(':
            nesting += 1
            if nesting > 1:
                current_arg.append(tok)
        elif tok.value == ')':
            nesting -= 1
            if nesting == 0:
                if current_arg:
                    args.append(trim_arg(current_arg))
                return args, i + 1
            else:
                current_arg.append(tok)
        elif tok.value == ',':
            if nesting == 1:
                args.append(trim_arg(current_arg))
                current_arg = []
            else:
                current_arg.append(tok)
        else:
            current_arg.append(tok)
        i += 1

def expand_tokens(macros, expr, depth=0):
    assert isinstance(expr, list)
    indent = "    " * depth
    print(indent + "Expression '{}'".format(expr))
    result = []
    expanded = False
    i = 0
    print("EXPR", expr)
    while i < len(expr):
        token = expr[i]
        if token.type == 'IDENTIFIER':
            if token.value in macros:
                macro = macros[token.value]
                if macro.params is not None:
                    args, offset = collect_args(expr[i+1:])
                    print("ARGS: ", args, offset)
                    if args is not None:
                        i += offset
                        result.extend(macros[token.value].subst(macros, args, depth))
                    else:
                        expanded = False
                        result.append(token)
                        i += 1
                        continue
                else:
                    result.extend(macros[token.value].expr)
                expanded = True
            else:
                result.append(token)
        elif token.type == 'WHITESPACE':
            token.value = ' '
            result.append(token)
        else:
            result.append(token)
        i += 1
    return expand_tokens(macros, result, depth+1) if expanded else result

def expand(macros, expr):
    expr = expr.replace('\\\n', '')
    if '\n' in expr:
        raise Exception("Newline in expression.")
    assert isinstance(expr, str)
    expanded = expand_tokens(macros, tokenize(expr))
    return "".join(e.value for e in expanded)

    
if __name__ == '__main__':
    noMacros = dict()
    dummyMacros = dict(DUMMY1=Macro(None, "dummy1"),
        DUMMY2=Macro([], "dummy2"), DUMMY3=Macro(["x"], "dummy3"),
        DUMMY4=Macro(["x", "y"], "dummy4"))

    # Simple do-nothing no-macro expansion.
    for macros in [noMacros, dummyMacros]:
        assert expand(macros, "AAA") == "AAA"
        assert expand(macros, "AAA()") == "AAA()"
        assert expand(macros, "5") == "5"
        assert expand(macros, "trla-baba lan") == "trla-baba lan"

    # Spaces between preprocessing tokens & inside string literals.
    # Implementation note:
    #   We wish to match MS Visual C++ compiler behaviour here which includes
    # replacing consecutive whitespace (other than new-line) between
    # preprocessing tokens with a single space character. Standard allows the
    # implementation to retain whitespace between preprocessing tokens as well.
    #                                                (30.04.2013.) (Jurko)
    assert expand(noMacros, "trla-baba   lan") == "trla-baba lan"
    assert expand(noMacros, '"trla-baba   lan"') == '"trla-baba   lan"'
    try:
        expand(noMacros, "trla-baba  \n   lan")
    except:
        pass
    else:
        assert False

    # Simple macro expansions.
    assert expand(dict(AAA=Macro(None, "5")), "AAA") == "5"
    assert expand(dict(AAA=Macro(None, "55")), "AAA") == "55"
    assert expand(dict(AAA=Macro([], "555")), "AAA()") == "555"

    # Chained macro expansion.
    assert expand(dict(AAA=Macro(None, "BBB"), BBB=Macro(None, "44")), "AAA")  \
        == "44"
    assert expand(dict(AAA=Macro(None, "BBB"), BBB=Macro(None, "CCC"),
        CCC=Macro(None, "treasure")), "AAA") == "treasure"

    # Escaped new-line handling..
    assert expand(noMacros, "trla-baba \\\n  lan") == "trla-baba lan"
    assert expand(noMacros, "trla-baba\\\nlan") == "trla-babalan"
    assert expand(noMacros, '"trla-baba  \\\n  lan"') == '"trla-baba    lan"'
    assert expand(dict(AAA=Macro(None, "555\\\n\\\n\\\n   666")), "AAA") ==  \
        "555 666"
    assert expand(dict(AAA=Macro(None, '"555\\\n\\\n\\\n   666"')), "AAA") ==  \
        '"555   666"'

    # Function & object-like macro call syntax mismatch.
    assert expand(dict(AAA=Macro([], "555")), "AAA") == "AAA"
    assert expand(dict(AAA=Macro(None, "555")), "AAA()") == "555()"
    
    # Function-like macro parameter substitution.
    assert expand(dict(AAA=Macro(["x"], "x")), "AAA(555)") == "555"
    assert expand(dict(AAA=Macro(["x"], "xx")), "AAA(555)") == "xx"
    assert expand(dict(AAA=Macro(["x"], "x;x")), "AAA(555)") == "555;555"

    # Preprocessing token concatenation.
    assert expand(dict(AAA=Macro(["x", "y"], "AA##BB")), "AAA(5,6)") == "AABB"
    assert expand(dict(AAA=Macro(["x", "y"], "x##BB")), "AAA(5,6)") == "5BB"
    assert expand(dict(AAA=Macro(["x", "y"], "AA##y")), "AAA(5,6)") == "AA6"
    assert expand(dict(AAA=Macro(["x", "y"], "x##y")), "AAA(5,6)") == "56"
    assert expand(dict(AAA=Macro(["x", "y"], "y##x")), "AAA(5,6)") == "65"
    assert expand(dict(AAA=Macro(["x", "y"], "x##x")), "AAA(5,6)") == "55"

    # Whitespace with preprocessing token concatenation.
    assert expand(dict(AAA=Macro(["x", "y"], "  x   ##   \\\ny   ")),
        "AAA(5,6)") == "56"

    # Passing an expanded macro to itself as a parameter.
    assert expand(dict(A=Macro(['x'], "x")), "A(A(A(A(A(treasure)))))") ==  \
        "treasure"

    # Whitespace in macro parameters.
    assert expand(dict(A=Macro(['x'], "x")), "A(A(ttt ))") == "ttt"
    assert expand(dict(A=Macro(['x'], "x")), "A(A(ttt  ))") == "ttt"
    assert expand(dict(A=Macro(['x'], "x")), "A(A( ttt))") == "ttt"
    assert expand(dict(A=Macro(['x'], "x")), "A(A(  ttt))") == "ttt"
    assert expand(dict(A=Macro(['x'], "x")), "A(A(   ttt     ))") == "ttt"
    assert expand(dict(A=Macro(['x'], "x")), "A(A( t   t  t   ))") == "t t t"
    assert expand(dict(A=Macro(['x'], "x")), 'A(A(t  "t  t" ))') == 't "t  t"'
    assert expand(dict(A=Macro(['x'], "x")), 'A(A(t  "t  \\\nt" ))') == 't "t  t"'

    # Expansion after macro concatenation.
    concatMacros = dict(A=Macro(None, "1"), B=Macro(None, "2"), AB=Macro(None,
        "tupko"), MERGE=Macro(None, "A##B"), MERGE2=Macro(["x", "y"], "x##y"))
    assert expand(concatMacros, "A##B") == "1##2"

    #TODO: escaped quotes in string literals