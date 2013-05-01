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

class Identifier: expr = r"[a-zA-Z_]\w*"
class Whitespace: expr = r"(//.*)|(/\*(.|\n)*?\*/)|\s" # Treat comments as whitespace too
class String:     expr = r"\"(?:[^\"\\]|\\.)*\"|<[^>]*>"
class Digits:     expr = r"[0-9]+"
class Bracket:    expr = r"[\(\)]"
class Comma:      expr = r","     
class HashHash:   expr = r"##"    
class Hash:       expr = r"#"     
class Other:      expr = r"."     

# Order is important here
token_types = (
    Identifier, Whitespace, String,
    Digits    , Bracket   , Comma ,
    HashHash  , Hash      , Other ,
)

def scanner_lexicon(token_type):
    return token_type.expr, lambda scanner, value: Token(token_type, value)

scanner = re.Scanner([(scanner_lexicon(token_type)) for token_type in token_types])

def tokenize(expr):
    result, remainder = scanner.scan(expr)
    if remainder:
        raise Exception("Got unexpected remainder '{}'.".format(remainder))
    return result


class Macro:
    def __init__(self, params, expr):
        self.params = params
        self.variadic = False
        if self.params:
            if '...' in self.params[:-1]:
                raise ValueError("Invalid elipsis in macro parameters")
            if self.params[-1] == '...':
                self.params[-1] = '__VA_ARGS__'
                self.variadic = True
        self.expr = tokenize(expr.replace("\\\n", '').strip())
        self.tokens_to_expand = []
        self.tokens_to_stringize = []
        self.tokens_to_catenate = []
        last = None
        skip_expand = False
        last_was_cat = None
        last_was_str = None
        i = 0
        while i < len(self.expr):
            token = self.expr[i]
            if token.type not in [Whitespace]:
                if last_was_str is not None:
                    if token.type == Identifier and params and token.value in self.params:
                        del self.expr[last_was_str]
                        i -= 1
                        self.tokens_to_stringize.append(i)
                        skip_expand = True
                if last_was_cat is not None:
                    assert self.expr[last_was_cat].type == HashHash
                    del self.expr[last_was_cat]
                    i -= 1
                    skip_expand = True
                    assert(last != i)
                    self.tokens_to_catenate.append((last, i))
                last_was_str = None
                last_was_cat = None

            if token.type not in [Whitespace, Hash, HashHash]:
                last = i

            if token.type == Identifier:
                if self.params and token.value in self.params and not skip_expand:
                    self.tokens_to_expand.append(i)
                skip_expand = False

            elif token.type == Hash:
                last_was_str = i

            if token.type == HashHash:
                last_was_cat = i
                if self.tokens_to_expand and self.tokens_to_expand[-1] == last:
                    del self.tokens_to_expand[-1]
            i += 1
        # Catenation will remove tokens thus destroying all trailing indices.
        # Make sure we are catenating right-to-left.
        # TODO: Ugly
        self.tokens_to_catenate.reverse()

    def subst(self, macros, args, depth):
        required = len(self.params)
        if self.variadic:
            required -= 1
        if len(args) < required:
            args.extend([[Token(Other, '')] for x in range(required-len(args))])
        result = []
        for i in range(len(self.expr)):
            token = self.expr[i]
            if token.type == Identifier and token.value in self.params:
                if self.variadic and token.value == '__VA_ARGS__':
                    first = True
                    for i in range(len(self.params) - 1, len(args)):
                        if not first:
                            result.append([Token(Other, ',')])
                        result.append(args[i])
                        first = False
                else:
                    to_add = args[self.params.index(token.value)]
                    if i in self.tokens_to_expand:
                        to_add = expand_tokens(macros, to_add, depth)
                    result.append(to_add)
            elif token.type == Whitespace:
                token.value = ' '
                result.append([token])
                while i + 1 < len(self.expr) and self.expr[i+1].type == Whitespace:
                    i += 1
            else:
                result.append([token])
        assert self.variadic or len(result) == len(self.expr)
        self.process_stringize(result)
        self.process_catenate(result)
        return list(itertools.chain(*result))

    def process_stringize(self, result):
        for i in self.tokens_to_stringize:
            assert len(result[i]) == 1
            result[i][0].value = '"{}"'.format(result[i][0].value)

    def process_catenate(self, result):
        """
            The result parameter is actually a list of lists. Each internal list
            is a token after parameter substitution. This way indices which need
            to be catenated are preserved.
        """
        for a, b in self.tokens_to_catenate:
            assert a < b
            assert len(result[a]) >= 1 and len(result[b]) >= 1
            if result[a][-1].type == Identifier and (result[b][0].type in (Identifier, Digits)):
                # Make sure we create a new identifier in this case.
                result[a][-1].value += result[b][0].value
                result[a].extend(result[b][1:])
            else:
                # Two separate tokens are OK.
                result[a].extend(result[b])
                # TODO:
                # In case catenate does not yield a valid preprocessor token
                # MSVC C++ preprocessor simply removes ## and expands the entire
                # expression. For example, given
                # #define A 1
                # #define B 2
                # #define CAT(a,b) a##b
                # CAT((A),B) becomes (1)2
                # We do not emulate this behavior here, but there is a
                # (disabled) test below.
            # Get rid of all whitespace and '##' inbetween
            del result[a+1:b+1]
                
def trim_tokens(what):
    while what and what[0].type == Whitespace:
        del what[0]
    while what and what[-1].type == Whitespace:
        del what[-1]
    return what

def collect_args(tokens):
    i = 0
    while i < len(tokens) and tokens[i].type == Whitespace:
        i += 1

    if i == len(tokens) or tokens[i].value != '(':
        return None, 0
    nesting = 0
    args = []
    current_arg = []
    
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
                    args.append(trim_tokens(current_arg))
                return args, i + 1
            else:
                current_arg.append(tok)
        elif tok.value == ',':
            if nesting == 1:
                args.append(trim_tokens(current_arg))
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
    expr = trim_tokens(expr)
    while i < len(expr):
        token = expr[i]
        if token.type == Identifier:
            if token.value in macros:
                macro = macros[token.value]
                if macro.params is not None:
                    args, offset = collect_args(expr[i+1:])
                    if args is not None:
                        i += offset
                        result.extend(macros[token.value].subst(macros, args, depth))
                    else:
                        expanded = False
                        result.append(token)
                        i += 1
                        continue
                else:
                    tokens = [[tok] for tok in macros[token.value].expr]
                    macros[token.value].process_catenate(tokens)
                    result.extend(list(itertools.chain(*tokens)))
                expanded = True
            else:
                result.append(token)
        elif token.type == Whitespace:
            token.value = ' '
            result.append(token)
            while i + 1 < len(expr) and expr[i+1].type == Whitespace:
                i += 1
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
    enable_tests_for_unsupported_features = False

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

    # Spaces between preprocessing tokens & inside string/header-name literals.
    # Implementation note:
    #   We wish to match MS Visual C++ compiler behaviour here which includes
    # replacing consecutive whitespace (other than new-line) between
    # preprocessing tokens with a single space character. Standard allows the
    # implementation to retain whitespace between preprocessing tokens as well.
    #                                                (30.04.2013.) (Jurko)
    assert expand(noMacros, "trla-baba   lan") == "trla-baba lan"
    assert expand(noMacros, '"trla-baba   lan"') == '"trla-baba   lan"'
    assert expand(noMacros, "<trla-baba   lan>") == "<trla-baba   lan>"
    try:
        expand(noMacros, "trla-baba  \n   lan")
    except Exception:
        pass
    else:
        assert False

    # Criss-crossed quote and angle-bracket header-name literals.
    # Implementation note:
    #   We wish to match MS Visual C++ compiler behaviour here, therefore
    # allowing quotes insided header-names specified using angle-brackets.
    # Standard states this results in undefined behaviour. Standard also states
    # mismatched quotes result in undefined behaviour.
    #                                                (30.04.2013.) (Jurko)
    assert expand(noMacros, 'a  "trla-baba   <lan"   b>   c') ==  \
        'a "trla-baba   <lan" b> c'
    assert expand(noMacros, 'a  <trla-baba   "lan>   b"   c') ==  \
        'a <trla-baba   "lan> b" c'
    assert expand(noMacros, 'a  "trla-baba   <lan  >  b"  c') ==  \
        'a "trla-baba   <lan  >  b" c'
    assert expand(noMacros, 'a  <trla-baba   "lan  "  b>  c') ==  \
        'a <trla-baba   "lan  "  b> c'

    # Escaped quotes in string literals.
    assert expand(noMacros, '"trla-b   \\"   l"') == '"trla-b   \\"   l"'
    assert expand(noMacros, '"trla-\\"b      l"') == '"trla-\\"b      l"'
    assert expand(noMacros, '"trla-\\"b   \\"   l"') == '"trla-\\"b   \\"   l"'

    # Simple macro expansions.
    assert expand(dict(AAA=Macro(None, "5")), "AAA") == "5"
    assert expand(dict(AAA=Macro(None, "55")), "AAA") == "55"
    assert expand(dict(AAA=Macro([], "555")), "AAA()") == "555"

    # Chained macro expansion.
    assert expand(dict(A=Macro(None, "B"), B=Macro(None, "44")), "A") == "44"
    assert expand(dict(A=Macro(None, "B"), B=Macro(None, "C"), C=Macro(None,  \
        "treasure")), "A") == "treasure"

    # Macros must not be expanded inside string & header-name literals.
    assert expand(dict(A=Macro(None, "x")), '"A"') == '"A"'
    assert expand(dict(A=Macro(None, "x")), 'A"A"') == 'x"A"'
    assert expand(dict(A=Macro(None, "x")), '"A"A') == '"A"x'
    assert expand(dict(A=Macro(None, "x")), 'A"A"A') == 'x"A"x'
    assert expand(dict(A=Macro(None, "x")), "<A>") == "<A>"
    assert expand(dict(A=Macro(None, "x")), "A<A>") == "x<A>"
    assert expand(dict(A=Macro(None, "x")), "<A>A") == "<A>x"
    assert expand(dict(A=Macro(None, "x")), "A<A>A") == "x<A>x"

    # Escaped new-line handling.
    assert expand(noMacros, "trla-baba \\\n  lan") == "trla-baba lan"
    assert expand(noMacros, "trla-baba\\\nlan") == "trla-babalan"
    assert expand(noMacros, '"trla-baba  \\\n  lan"') == '"trla-baba    lan"'
    assert expand(dict(A=Macro(None, "555\\\n\\\n\\\n   666")), "A") ==  \
        "555 666"
    assert expand(dict(A=Macro(None, '"555\\\n\\\n\\\n   666"')), "A") ==  \
        '"555   666"'

    # Function-like macro parameter substitution.
    assert expand(dict(AAA=Macro(["x"], "x")), "AAA(555)") == "555"
    assert expand(dict(AAA=Macro(["x"], "xx")), "AAA(555)") == "xx"
    assert expand(dict(AAA=Macro(["x"], "x;x")), "AAA(555)") == "555;555"
    assert expand(dict(A=Macro(["x", "xx"], "xx;x;xx")), "A(5,9)") == "9;5;9"
    assert expand(dict(A=Macro(["xx", "x"], "xx;x;xx")), "A(5,9)") == "5;9;5"
    assert expand(dict(A=Macro(["xx", "x"], "xxx;xx")), "A(5,9)") == "xxx;5"
    assert expand(dict(A=Macro(["xx", "x"], "xx;xxx")), "A(5,9)") == "5;xxx"

    # Comments replaced with a single space character.
    assert expand(noMacros, "puff/* unga */daddy") == "puff daddy"
    assert expand(noMacros, "puff /* unga */ daddy") == "puff daddy"
    assert expand(noMacros, "puff daddy  // Wake the dragon.") == "puff daddy"

    # Multi-line comments.
    assert expand(noMacros, "puff/*a\\\nb\\\n\\\ncc*/daddy") == "puff daddy"
    assert expand(noMacros, "puff daddy// ...\\\na\\\n\\\ncc") == "puff daddy"

    # Recursive comments.
    assert expand(noMacros, "puff /* un //ga */ daddy") == "puff daddy"
    assert expand(noMacros, "puff /* un /* ga */ daddy") == "puff daddy"
    assert expand(noMacros, "puff /* un // ga */ daddy") == "puff daddy"
    assert expand(noMacros, "puff /* un /* ga */ y */ dad") == "puff y */ dad"
    assert expand(noMacros, "puff daddy // a /* b */") == "puff daddy"
    assert expand(noMacros, "puff daddy // a // b /* c */") == "puff daddy"

    # Macros defined with an included comment.
    assert expand(dict(A=Macro(None, "x // Spiffin")), "A") == "x"
    assert expand(dict(A=Macro(None, "x/* Spiffin */")), "A") == "x"
    assert expand(dict(A=Macro(None, "/* Spiffin */x")), "A") == "x"
    assert expand(dict(A=Macro(None, "x/* Spiffin */y")), "A") == "x y"
    assert expand(dict(A=Macro(None, "x /* Spiffin */ y")), "A") == "x y"

    # Macros must not be expanded inside comments.
    assert expand(dict(A=Macro(None, "x /* Spiffin B z */ y"), B=Macro(None,
        "*/")), "A") == "x y"

    # Preprocessing token concatenation.
    assert expand(dict(AAA=Macro(["x", "y"], "AA##BB")), "AAA(5,6)") == "AABB"
    assert expand(dict(AAA=Macro(["x", "y"], "x##BB")), "AAA(5,6)") == "5BB"
    assert expand(dict(AAA=Macro(["x", "y"], "AA##y")), "AAA(5,6)") == "AA6"
    assert expand(dict(AAA=Macro(["x", "y"], "x##y")), "AAA(5,6)") == "56"
    assert expand(dict(AAA=Macro(["x", "y"], "y##x")), "AAA(5,6)") == "65"
    assert expand(dict(AAA=Macro(["x", "y"], "x##x")), "AAA(5,6)") == "55"

    # Whitespace with preprocessing token concatenation.
    assert expand(dict(AAA=Macro(["x", "y"], "  x   ##   \\\ny   ")),  \
        "AAA(5,6)") == "56"

    # Passing an expanded macro to itself as a parameter.
    assert expand(dict(A=Macro(["x"], "x")), "A(A(A(A(A(treasure)))))") ==  \
        "treasure"

    # Whitespace in macro parameters.
    assert expand(dict(A=Macro(["x"], "x")), "A(ttt )") == "ttt"
    assert expand(dict(A=Macro(["x"], "x")), "A(ttt  )") == "ttt"
    assert expand(dict(A=Macro(["x"], "x")), "A( ttt)") == "ttt"
    assert expand(dict(A=Macro(["x"], "x")), "A(  ttt)") == "ttt"
    assert expand(dict(A=Macro(["x"], "x")), "A(   ttt     )") == "ttt"
    assert expand(dict(A=Macro(["x"], "x")), "A( t   t  t   )") == "t t t"
    assert expand(dict(A=Macro(["x"], "x")), 'A(t  "t  t" )') == 't "t  t"'
    assert expand(dict(A=Macro(["x"], "x")), 'A(t  "t  \\\nt" )') == 't "t  t"'

    # Expansion after macro concatenation.
    concatMacros = dict(A=Macro(None, "1"), B=Macro(None, "2"), AB=Macro(None,
        "tupko"), MERGE=Macro(None, "A##B"), MERGE2=Macro(["x", "y"], "x##y"))
    assert expand(concatMacros, "A##B") == "1##2"
    assert expand(concatMacros, "MERGE") == "tupko"
    assert expand(concatMacros, "MERGE2(A, B)") == "tupko"
    # Non-standard MS VC++ behaviour we currently do not emulate.
    if enable_tests_for_unsupported_features:
        assert expand(concatMacros, "MERGE2((A), B)") == "(1)2"
        assert expand(concatMacros, "MERGE2(A, (B))") == "1(2)"
        assert expand(concatMacros, "MERGE2((A), (B))") == "(1)(2)"

    # Arguments in parentheses containing a comma.
    bingoMacros = dict(A=Macro(["x", "y"], "x bingo y"))
    assert expand(bingoMacros, "A(1, 2)") == "1 bingo 2"
    assert expand(bingoMacros, "A((1), 2)") == "(1) bingo 2"
    assert expand(bingoMacros, "A((1, 3), 2)") == "(1, 3) bingo 2"
    assert expand(bingoMacros, "A((1, 3), (2, 15, 7, 2))") ==  \
        "(1, 3) bingo (2, 15, 7, 2)"

    # Function & object-like macro call syntax mismatch.
    assert expand(dict(AAA=Macro([], "555")), "AAA") == "AAA"
    assert expand(dict(AAA=Macro(None, "555")), "AAA()") == "555()"
    assert expand(dict(A=Macro(None, "pip")), "A(2)") == "pip(2)"
    assert expand(dict(A=Macro(None, "pip"), B=Macro(None, "A(22)")), "B(9)")  \
        == "pip(22)(9)"

    # Stringize constant.
    stringizeMacros = dict(S=Macro(["x"], "S2(x)"), S2=Macro(["x"], "#x"))
    assert expand(noMacros, "#AAA") == "#AAA"
    assert expand(dict(AAA=Macro(None, "1")), "#AAA") == "#1"
    assert expand(dict(AAA=Macro(["x"], "1")), "#AAA") == "#AAA"
    assert expand(dict(AAA=Macro(["x"], "1")), "#AAA(5)") == "#1"
    assert expand(dict(AAA=Macro(["x"], "#x")), "AAA(55)") == '"55"'
    assert expand(dict(AAA=Macro(["x"], "ge#x fu")), "AAA(55)") == 'ge"55" fu'
    assert expand(dict(AAA=Macro(["x"], "ge#xfu")), "AAA(55)") == 'ge#xfu'
    assert expand(stringizeMacros, "S2(B)") == '"B"'
    assert expand(stringizeMacros, "S(B)") == '"B"'

    # Stringize macro value.
    macros = stringizeMacros.copy()
    macros.update(B=Macro(None, "0"))
    assert expand(macros, "S2(B)") == '"B"'
    assert expand(macros, "S(B)") == '"0"'

    # Passing function-like macro name as parameter.
    assert expand(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x()"), BBB=Macro(["x"], "AAA(x)")), "BBB(B)") == "10"

    # More complex function-like parameter substitution tests.
    assert expand(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x"), BBB=Macro(["x"], "AAA(x)")), "AAA(B())") == "10"
    assert expand(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x"), BBB=Macro(["x"], "AAA(x)")), "BBB(B())") == "B5"

    # Variadic macros.
    assert expand(dict(A=Macro([], "__VA_ARGS__")), "A()") == "__VA_ARGS__"
    assert expand(dict(A=Macro([], "__VA_ARGS__")), "A(1, 2, 3)") ==  \
        "__VA_ARGS__"
    assert expand(dict(A=Macro(["..."], "__VA_ARGS__")), "A()") == ""
    assert expand(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1, 2, 3)") ==  \
        "1,2,3"
    assert expand(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1,2,3)") ==  \
        "1,2,3"
    assert expand(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1,2,   3)") ==  \
        "1,2,3"
    assert expand(dict(A=Macro(["x", "..."], "__VA_ARGS__")), "A(1, 2, 3)")  \
        == "2,3"
    assert expand(dict(A=Macro(["x", "y", "..."], "__VA_ARGS__")), "A(1, 2, 3)"
        ) == "3"
    assert expand(dict(A=Macro(["x", "y", "z", "..."], "__VA_ARGS__")),  \
        "A(1, 2, 3)") == ""
    assert expand(dict(A=Macro(["x", "y", "z", "..."], "__VA_ARGS__, z, y, x")
        ), "A(1, 2, 3)") == ", 3, 2, 1"

    # Invalid number of macro parameters.
    # Implementation note:
    #   We wish to match MS Visual C++ compiler behaviour here, therefore we
    # allow function-like macro expansions with an invalid number of parameters
    # by ignoring extra ones and expanding missing ones as empty strings.
    #                                                (30.04.2013.) (Jurko)
    assert expand(dict(A=Macro(["x", "y"], "a;x;y;b")), "A()") == "a;;;b"
    assert expand(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(1)") == "a;1;;b"
    assert expand(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(,2)") == "a;;2;b"
    assert expand(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(1,2,3)") ==  \
        "a;1;2;b"
    assert expand(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
        "A()") == "a;;;;b"
    assert expand(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
        "A(1)") == "a;1;;;b"
    assert expand(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
        "A(,2)") == "a;;2;;b"
    assert expand(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
        "A(,,,4)") == "a;;;,4;b"
