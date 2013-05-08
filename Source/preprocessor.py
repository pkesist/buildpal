#! python3
import copy
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

# Used internally
class Empty: pass

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


class ExpandedMacro:
    def __init__(self, value, macros):
        assert isinstance(value, tuple)
        assert all(isinstance(t, Token) for t in value)
        assert isinstance(macros, set) or isinstance(macros, frozenset)
        self.__value = value
        print("MACROS is ", macros)
        self.__expanded = frozenset(macros)
        print("MACROS gaga ", self.__expanded)

    def __eq__(self, other):
        return self.__value == other.__value and self.__expanded == other.__expanded

    def __hash__(self):
        return (self.__value, self.__expanded).__hash__()

    @property
    def value(self): return self.__value

    @property
    def expanded(self): return self.__expanded


class NotEnoughArguments(BaseException): pass

class Macro:
    @property
    def params(self):
        return self.__params

    @property
    def expr(self):
        return self.__expr

    @property
    def variadic(self):
        return self.__variadic

    def __repr__(self):
        return "<Macro object: Params '{}', Expr '{}'>".format(self.params, "".join([v.value for v in self.expr]))

    def __init__(self, params, expr):
        self.__params = params
        self.__variadic = False
        if self.__params:
            if '...' in self.__params[:-1]:
                raise ValueError("Invalid elipsis in macro parameters")
            if self.__params[-1] == '...':
                self.__params[-1] = '__VA_ARGS__'
                self.__variadic = True
        if not expr:
            self.__expr = None
            return
        self.__expr = tokenize(expr.replace("\\\n", '').strip())
        self.tokens_to_expand = []
        self.tokens_to_stringize = []
        self.tokens_to_catenate = []
        last = None
        skip_expand = False
        last_was_cat = None
        last_was_str = None
        i = 0
        while i < len(self.expr):
            token = self.__expr[i]
            if token.type not in [Whitespace]:
                if last_was_str is not None:
                    if token.type == Identifier and params and token.value in self.params:
                        del self.expr[last_was_str]
                        i -= 1
                        self.tokens_to_stringize.append(i)
                        skip_expand = True
                if last_was_cat is not None:
                    assert self.__expr[last_was_cat].type == HashHash
                    del self.__expr[last_was_cat]
                    i -= 1
                    skip_expand = True
                    assert(last != i)
                    self.tokens_to_catenate.append((last, i))
                last_was_str = None
                last_was_cat = None

            if token.type not in [Whitespace, Hash, HashHash]:
                last = i

            if token.type == Identifier:
                if self.__params and token.value in self.params and not skip_expand:
                    self.tokens_to_expand.append(i)
                skip_expand = False

            elif token.type == Hash:
                last_was_str = i

            if token.type == HashHash:
                last_was_cat = i
                if self.tokens_to_expand and self.tokens_to_expand[-1] == last:
                    del self.tokens_to_expand[-1]
            i += 1
        # Catenation will remove tokens thus destroying all trailing indices, so
        # make sure we are catenating right-to-left.
        # TODO: Ugly
        self.tokens_to_catenate.reverse()

    def subst(self, macros, args, depth, start=True, pos=0):
        required = len(self.params)
        if self.variadic:
            required -= 1
        if len(args) < required:
            raise NotEnoughArguments()
        prev_data = []
        i = pos
        while i < len(self.expr):
            token = self.expr[i]
            to_add = []
            if token.type == Identifier and token.value in self.params:
                arg_index = self.params.index(token.value)
                if self.variadic and token.value == '__VA_ARGS__':
                    first = True
                    for k in range(len(self.params) - 1, len(args)):
                        if not first:
                            to_add.append(Token(Comma, ','))
                        to_add.extend(args[k])
                        first = False
                    if not to_add:
                        to_add.append(Token(Empty, ''))
                else:
                    to_add = args[self.params.index(token.value)]
                if to_add and i in self.tokens_to_expand:
                    to_add = expand_tokens(macros, to_add, set(), True, depth)
                    assert isinstance(to_add, set)
                    assert all(isinstance(x, ExpandedMacro) for x in to_add)
                    to_add = [x.value for x in to_add]
                else:
                    to_add = [to_add]
                if i+1 < len(self.expr):
                    try:
                        tail = self.subst(macros, args, depth, False, i+1)
                    except NotEnoughArguments:
                        assert False and "Should never happen"
                else:
                    tail = [[]]

                result = []
                for possibility in tail:
                    for x in to_add:
                        x = [x]
                        if prev_data:
                            x = prev_data + x
                        result.append(x + possibility)

                if start:
                    for z in result:
                        self.process_stringize(z)
                        self.process_catenate(z)

                return result
            else:
                prev_data.append([token])
            i += 1
        assert self.variadic or len(prev_data) == len(self.expr[pos:])
        if start:
            self.process_stringize(prev_data)
            self.process_catenate(prev_data)
        return [prev_data]

    def process_stringize(self, result):
        for i in self.tokens_to_stringize:
            def token_str(t):
                if t.type == String:
                    return t.value.replace('\\', '\\\\').replace('"', '\\"')
                return t.value

            val = "".join(token_str(t) for t in result[i])
            val = '"{}"'.format(val)
            result[i] = [Token(String, val)]

    def process_catenate(self, result):
        """
            The result parameter is actually a list of lists. Each internal list
            is a token after parameter substitution. This way indices which need
            to be catenated are preserved.
        """
        for a, b in self.tokens_to_catenate:
            assert a < b
            if len(result[a]) >= 1 and len(result[b]) >= 1 and result[a][-1].type == Identifier and (result[b][0].type in (Identifier, Digits)):
                # Make sure we create a new identifier in this case.
                # This way we can avoid re-tokenizing every intermediate result.
                result[a][-1] = Token(Identifier, result[a][-1].value + result[b][0].value)
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
    first = 0
    while what[first:] and what[first].type == Whitespace: first += 1
    last = len(what)
    while what[:last-1] and what[last-1].type == Whitespace: last -= 1
    return what[first:last]

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

class UndefinedMacro: pass

def expand_tokens(macros, expr, expanded_macros, start=True, depth=0, debug=True):
    """
    Main worker for macro expansion.

    It will return a collection of 2-tuples. Each tuple is a possible expanded
    value, together with a set of macros which were expanded in the process.
    """
    assert expr
    assert isinstance(expr, list) or isinstance(expr, tuple)
    if expanded_macros is None:
        expanded_macros = set()
    indent = "    " * depth
    prev_data = []
    prev_depends = set()
    expanded = False
    i = 0
    if start:
        expr = trim_tokens(expr)
    if debug: print(indent + "Expanding", "".join([e.value for e in expr]))
    while i < len(expr):
        token = expr[i]
        if token.type == Identifier and token.value in macros and not token.value in expanded_macros:
            all_macro_values = set()
            all_new_expanded = set()

            tail_with_args = None
            tail_without_args = None
            if i + 1 < len(expr):
                args, offset = collect_args(expr[i+1:])
            else:
                args, offset = None, 0
            for macro in macros[token.value]:
                new_offset = i
                if macro.params is None or args is not None:
                    # We have enough data to expand this macro.
                    current_macro_values = []
                    if macro.params is None:
                        tokens = [[tok] for tok in macro.expr]
                        macro.process_catenate(tokens)
                        current_macro_values.append(list(itertools.chain(*tokens)))
                    else:
                        new_offset += offset
                        try:
                            substitute = macro.subst(macros, copy.deepcopy(args), depth)
                        except NotEnoughArguments:
                            # Substitution failure - ignore this macro and continue.
                            continue
                        for p in substitute:
                            current_macro_values.append(list(itertools.chain(*p)))

                    if new_offset + 1 < len(expr):
                        if tail_with_args is None:
                            tail_with_args = expand_tokens(macros, expr[new_offset+1:], expanded_macros, False, depth, debug)
                        all_macro_values.update((ExpandedMacro(tuple(prev_data + c) + exp_macro.value, frozenset(exp_macro.expanded | {(token.value, macro)}))) for c in current_macro_values for exp_macro in tail_with_args)
                    else:
                        all_macro_values.update((ExpandedMacro(tuple(prev_data + c), frozenset({(token.value, macro)}))) for c in current_macro_values)
                else:
                    # Degenerate case - we cannot expand this macro yet as it
                    # expects arguments and we have none (yet).
                    # We should expand anything following this macro as that
                    # might expand into argument list.
                    prev_data.append(token)
                    if new_offset + 1 < len(expr):
                        if tail_without_args is None:
                            tail_without_args = expand_tokens(macros, expr[new_offset + 1:], expanded_macros, False, depth, debug)
                        all_macro_values.update((ExpandedMacro(tuple(prev_data) + exp_macro.value, frozenset(exp_macro.expanded))) for exp_macro in tail_without_args)
                    else:
                        all_macro_values.add(ExpandedMacro(tuple(prev_data), frozenset()))
            if start:
                tmp = set()
                for expanded_macro in all_macro_values:
                    if not expanded_macro.value: continue
                    if expanded_macro.expanded:
                        for reexpanded_macro in expand_tokens(macros, expanded_macro.value, expanded_macros | expanded_macro.expanded, True, depth + 1, debug):
                            tmp.add(ExpandedMacro(reexpanded_macro.value, reexpanded_macro.expanded | expanded_macro.expanded | expanded_macros))
                    else:
                        tmp.add(ExpandedMacro(expanded_macro.value, frozenset(expanded_macros)))
                all_macro_values = tmp
            if debug:
                for expanded_macro in all_macro_values:
                    v = expanded_macro.value
                    e = expanded_macro.expanded
                    print(indent + "".join([e.value for e in expr]), "expanded to ", "".join([a.value for a in v]))
                    print(indent + "    It depends on:", e)
            return all_macro_values
        if token.type == Identifier:
            prev_data.append(token)
            prev_depends.add((token.value, UndefinedMacro))
        elif token.type == Whitespace:
            token.value = ' '
            prev_data.append(token)
            while i + 1 < len(expr) and expr[i+1].type == Whitespace:
                i += 1
        else:
            prev_data.append(token)
        i += 1
    return {ExpandedMacro(tuple(prev_data), frozenset(prev_depends))}

def expand_simple(macros, expr):
    expr = expr.replace('\\\n', '')
    if '\n' in expr:
        raise Exception("Newline in expression.")
    assert isinstance(expr, str)
    macros = dict((macro, [macros[macro]]) for macro in macros)
    data = expand_tokens(macros, tokenize(expr), set())
    assert(len(data) == 0 or len(data) == 1)
    if len(data) == 0:
        raise Exception("Macro expansion failure")
    for expanded_macro in data:
        return "".join(d.value for d in expanded_macro.value)

def expand_complex(macros, expr):
    expr = expr.replace('\\\n', '')
    if '\n' in expr:
        raise Exception("Newline in expression.")
    assert isinstance(expr, str)
    return [("".join(d.value for d in expanded_macro.value), expanded_macro.expanded) for expanded_macro in expand_tokens(macros, tokenize(expr), set())]
    
def tests():
    enable_tests_for_unsupported_features = False

    # Macro definition dictionaries shared between different tests.
    noMacros = dict()
    dummyMacros = dict(DUMMY1=Macro(None, "dummy1"),
        DUMMY2=Macro([], "dummy2"), DUMMY3=Macro(["x"], "dummy3"),
        DUMMY4=Macro(["x", "y"], "dummy4"))

    # Shortcuts for calling functions to be tested.
    e = expand_simple

    #   Macro may expand to arguments for another function-like macro
    # invocation, including parentheses.
    assert e(dict(AAA=Macro(["x"], "Jura the x"), BBB=Macro(None, "(fool)")),
        "AAA BBB") == "Jura the fool"
    assert e(dict(AAA=Macro(["x"], "Jura the x"), BBB=Macro(None, "(fool)"),
        CCC=Macro(None, "AAA BBB")), "CCC") == "Jura the fool"
    assert e(dict(AAA=Macro(["x", "y"], ":x:y:"), BBB=Macro(None, "(1,2)")),
        "AAA BBB") == ":1:2:"
    assert e(dict(AAA=Macro(["..."], ":__VA_ARGS__:"), BBB=Macro(None,  \
        "(1,2,3)")), "AAA BBB") == ":1,2,3:"
    assert e(dict(UNPARENTHESIZE=Macro(["..."], "__VA_ARGS__"), AAA=Macro(None,
        "(bingo)"), BBB=Macro(None, "UNPARENTHESIZE AAA")), "BBB") == "bingo"
    
    # Simple do-nothing no-macro expansion.
    for macros in [noMacros, dummyMacros]:
        assert e(macros, "AAA") == "AAA"
        assert e(macros, "AAA()") == "AAA()"
        assert e(macros, "5") == "5"
        assert e(macros, "trla-baba lan") == "trla-baba lan"

    # Spaces between preprocessing tokens & inside string/header-name literals.
    # Implementation note:
    #   We wish to match MS Visual C++ preprocessor behaviour here which
    # includes replacing consecutive whitespace (other than new-line) between
    # preprocessing tokens with a single space character. Standard allows the
    # implementation to retain whitespace between preprocessing tokens as well.
    #                                                (30.04.2013.) (Jurko)
    assert e(noMacros, "trla-baba   lan") == "trla-baba lan"
    assert e(noMacros, '"trla-baba   lan"') == '"trla-baba   lan"'
    assert e(noMacros, "<trla-baba   lan>") == "<trla-baba   lan>"
    try:
        e(noMacros, "trla-baba  \n   lan")
    except Exception:
        pass
    else:
        assert False

    # Criss-crossed quote and angle-bracket header-name literals.
    # Implementation note:
    #   We wish to match MS Visual C++ preprocessor behaviour here, therefore
    # allowing quotes insided header-names specified using angle-brackets.
    # Standard states this results in undefined behaviour. Standard also states
    # mismatched quotes result in undefined behaviour.
    #                                                (30.04.2013.) (Jurko)
    assert e(noMacros, 'a  "trla-baba   <lan"   b>   c') ==  \
        'a "trla-baba   <lan" b> c'
    assert e(noMacros, 'a  <trla-baba   "lan>   b"   c') ==  \
        'a <trla-baba   "lan> b" c'
    assert e(noMacros, 'a  "trla-baba   <lan  >  b"  c') ==  \
        'a "trla-baba   <lan  >  b" c'
    assert e(noMacros, 'a  <trla-baba   "lan  "  b>  c') ==  \
        'a <trla-baba   "lan  "  b> c'

    # Escaped quotes in string literals.
    assert e(noMacros, '"trla-b   \\"   l"') == '"trla-b   \\"   l"'
    assert e(noMacros, '"trla-\\"b      l"') == '"trla-\\"b      l"'
    assert e(noMacros, '"trla-\\"b   \\"   l"') == '"trla-\\"b   \\"   l"'

    # Simple macro expansions.
    assert e(dict(AAA=Macro(None, "5")), "AAA") == "5"
    assert e(dict(AAA=Macro(None, "55")), "AAA") == "55"
    assert e(dict(AAA=Macro([], "555")), "AAA()") == "555"

    # Chained macro expansion.
    assert e(dict(A=Macro(None, "B"), B=Macro(None, "44")), "A") == "44"
    assert e(dict(A=Macro(None, "B"), B=Macro(None, "C"), C=Macro(None,  \
        "treasure")), "A") == "treasure"

    # Macro names are case sensitive.
    assert e(dict(AaA=Macro(None, "5")), "AaA") == "5"
    assert e(dict(AaA=Macro(None, "5")), "aaa") == "aaa"
    assert e(dict(AaA=Macro(None, "5")), "AAA") == "AAA"

    # Macros must not be expanded inside string & header-name literals.
    assert e(dict(A=Macro(None, "x")), '"A"') == '"A"'
    assert e(dict(A=Macro(None, "x")), 'A"A"') == 'x"A"'
    assert e(dict(A=Macro(None, "x")), '"A"A') == '"A"x'
    assert e(dict(A=Macro(None, "x")), 'A"A"A') == 'x"A"x'
    assert e(dict(A=Macro(None, "x")), "<A>") == "<A>"
    assert e(dict(A=Macro(None, "x")), "A<A>") == "x<A>"
    assert e(dict(A=Macro(None, "x")), "<A>A") == "<A>x"
    assert e(dict(A=Macro(None, "x")), "A<A>A") == "x<A>x"

    # Escaped new-line handling.
    assert e(noMacros, "trla-baba \\\n  lan") == "trla-baba lan"
    assert e(noMacros, "trla-baba\\\nlan") == "trla-babalan"
    assert e(noMacros, '"trla-baba  \\\n  lan"') == '"trla-baba    lan"'
    assert e(dict(A=Macro(None, "555\\\n\\\n\\\n   666")), "A") == "555 666"
    assert e(dict(A=Macro(None, '"555\\\n\\\n\\\n   666"')), "A") ==  \
        '"555   666"'

    # Function-like macro parameter substitution.
    assert e(dict(AAA=Macro(["x"], "x")), "AAA(555)") == "555"
    assert e(dict(AAA=Macro(["x"], "xx")), "AAA(555)") == "xx"
    assert e(dict(AAA=Macro(["x"], "x;x")), "AAA(555)") == "555;555"
    assert e(dict(A=Macro(["x", "xx"], "xx;x;xx")), "A(5,9)") == "9;5;9"
    assert e(dict(A=Macro(["xx", "x"], "xx;x;xx")), "A(5,9)") == "5;9;5"
    assert e(dict(A=Macro(["xx", "x"], "xxx;xx")), "A(5,9)") == "xxx;5"
    assert e(dict(A=Macro(["xx", "x"], "xx;xxx")), "A(5,9)") == "5;xxx"
    assert e(dict(AAA=Macro(["x"], "x")), 'AAA(")")') == '")"'

    # Whitespace between macro name and its parameter.
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here. MS VC++
    # preprocessor keeps this whitespace as-is while we merge it into a single
    # one.
    #                                                (02.05.2013.) (Jurko)
    assert e(dict(AAA=Macro(None, "treasure")), "AAA  ()") == "treasure ()"
    assert e(dict(AAA=Macro([], "treasure")), "AAA  ()") == "treasure"

    # Whitespace around macro definition.
    assert e(dict(AAA=Macro(None, "  BBB  ")), "AAA") == "BBB"
    assert e(dict(AAA=Macro([], "  BBB  ")), "AAA()") == "BBB"
    assert e(dict(AAA=Macro(["x"], "  BBB  ")), "AAA(5)") == "BBB"

    # Comments replaced with a single space character.
    assert e(noMacros, "puff/* unga */daddy") == "puff daddy"
    assert e(noMacros, "puff /* unga */ daddy") == "puff daddy"
    assert e(noMacros, "puff daddy  // Wake the dragon.") == "puff daddy"

    # Multi-line comments.
    assert e(noMacros, "puff/*a\\\nb\\\n\\\ncc*/daddy") == "puff daddy"
    assert e(noMacros, "puff daddy// ...\\\na\\\n\\\ncc") == "puff daddy"

    # Recursive comments.
    assert e(noMacros, "puff /* un //ga */ daddy") == "puff daddy"
    assert e(noMacros, "puff /* un /* ga */ daddy") == "puff daddy"
    assert e(noMacros, "puff /* un // ga */ daddy") == "puff daddy"
    assert e(noMacros, "puff /* un /* ga */ y */ dad") == "puff y */ dad"
    assert e(noMacros, "puff daddy // a /* b */") == "puff daddy"
    assert e(noMacros, "puff daddy // a // b /* c */") == "puff daddy"

    # Macros defined with an included comment.
    assert e(dict(A=Macro(None, "x // Spiffin")), "A") == "x"
    assert e(dict(A=Macro(None, "x/* Spiffin */")), "A") == "x"
    assert e(dict(A=Macro(None, "/* Spiffin */x")), "A") == "x"
    assert e(dict(A=Macro(None, "x/* Spiffin */y")), "A") == "x y"
    assert e(dict(A=Macro(None, "x /* Spiffin */ y")), "A") == "x y"

    # Macros must not be expanded inside comments.
    assert e(dict(A=Macro(None, "x /* Spiffin B z */ y"), B=Macro(None, "*/")),
        "A") == "x y"

    # Preprocessing token concatenation.
    assert e(dict(AAA=Macro(["x", "y"], "AA##BB")), "AAA(5,6)") == "AABB"
    assert e(dict(AAA=Macro(["x", "y"], "x##BB")), "AAA(5,6)") == "5BB"
    assert e(dict(AAA=Macro(["x", "y"], "AA##y")), "AAA(5,6)") == "AA6"
    assert e(dict(AAA=Macro(["x", "y"], "x##y")), "AAA(5,6)") == "56"
    assert e(dict(AAA=Macro(["x", "y"], "y##x")), "AAA(5,6)") == "65"
    assert e(dict(AAA=Macro(["x", "y"], "x##x")), "AAA(5,6)") == "55"

    # Whitespace with preprocessing token concatenation.
    assert e(dict(AAA=Macro(["x", "y"], "  x   ##   \\\ny   ")), "AAA(5,6)")  \
        == "56"

    # Passing an expanded macro to itself as a parameter.
    assert e(dict(A=Macro(["x"], "x")), "A(A(A(A(A(diamond)))))") == "diamond"

    # Whitespace in macro parameters.
    assert e(dict(A=Macro(["x"], "x")), "A(ttt )") == "ttt"
    assert e(dict(A=Macro(["x"], "x")), "A(ttt  )") == "ttt"
    assert e(dict(A=Macro(["x"], "x")), "A( ttt)") == "ttt"
    assert e(dict(A=Macro(["x"], "x")), "A(  ttt)") == "ttt"
    assert e(dict(A=Macro(["x"], "x")), "A(   ttt     )") == "ttt"
    assert e(dict(A=Macro(["x"], "x")), "A( t   t  t   )") == "t t t"
    assert e(dict(A=Macro(["x"], "x")), 'A(t  "t  t" )') == 't "t  t"'
    assert e(dict(A=Macro(["x"], "x")), 'A(t  "t  \\\nt" )') == 't "t  t"'

    # Stringize constant.
    assert e(noMacros, "#AAA") == "#AAA"
    assert e(dict(AAA=Macro(None, "1")), "#AAA") == "#1"
    assert e(dict(AAA=Macro(["x"], "1")), "#AAA") == "#AAA"
    assert e(dict(AAA=Macro(["x"], "1")), "#AAA(5)") == "#1"
    assert e(dict(AAA=Macro(["x"], "#x")), "AAA(55)") == '"55"'
    assert e(dict(AAA=Macro(["x"], "ge#xfu")), "AAA(55)") == 'ge#xfu'
    assert e(dict(AAA=Macro(["x"], "ge#x fu")), "AAA(55)") == 'ge"55" fu'
    assert e(dict(AAA=Macro(["x"], "ge#x)fu")), "AAA(55)") == 'ge"55")fu'
    assert e(dict(AAA=Macro(["x"], "ge#(x)fu")), "AAA(55)") == 'ge#(55)fu'
    assert e(dict(AAA=Macro(["x"], "ge(#x)fu")), "AAA(55)") == 'ge("55")fu'
    stringizeMacros = dict(S=Macro(["x"], "S2(x)"), S2=Macro(["x"], "#x"))
    assert e(stringizeMacros, "S(B)") == '"B"'
    assert e(stringizeMacros, "S2(B)") == '"B"'
    assert e(stringizeMacros, "S2(pi pU)") == '"pi pU"'

    # Stringized quotes & backslashes inside string literals.
    assert e(stringizeMacros, r'S2("")') == r'"\"\""'
    assert e(stringizeMacros, r'S2("B")') == r'"\"B\""'
    assert e(stringizeMacros, r"S2(\B)") == r'"\B"'
    assert e(stringizeMacros, r'S2("\B")') == r'"\"\\B\""'

    # Stringize macro value.
    macros = stringizeMacros.copy()
    macros.update(B=Macro(None, "0"), C=Macro([], "1"))
    assert e(macros, "S2(B)") == '"B"'
    assert e(macros, "S(B)") == '"0"'
    assert e(macros, "S2(B())") == '"B()"'
    assert e(macros, "S(B())") == '"0()"'
    assert e(macros, "S2(C)") == '"C"'
    assert e(macros, "S(C)") == '"C"'
    assert e(macros, "S2(C())") == '"C()"'
    assert e(macros, "S(C())") == '"1"'

    #   Hash not treated as a stringize preprocessor operator treated as in
    # object-like macros as well as function-like macros with no input
    # parameters.
    assert e(dict(HASH=Macro(None, "#")), "HASH") == "#"
    assert e(dict(A=Macro(None, "#B")), "A") == "#B"
    assert e(dict(A=Macro(None, "#B"), B=Macro(None, "0")), "A") == "#0"
    assert e(dict(HASH=Macro([], "#")), "HASH()") == "#"
    assert e(dict(A=Macro([], "#B")), "A()") == "#B"
    assert e(dict(A=Macro([], "#B"), B=Macro(None, "0")), "A()") == "#0"

    # Expansion after macro concatenation.
    concatMacros = stringizeMacros.copy()
    concatMacros.update(
        A=Macro(None, "1"),
        B=Macro(None, "2"),
        AB=Macro(None, "tupko"),
        MERGE=Macro(None, "A##B"),
        MERGE2=Macro(["x", "y"], "x##y"),
        STRINGIZE_MERGE2=Macro(["x", "y"], "S2(x##y)"))
    assert e(concatMacros, "A##B") == "1##2"
    assert e(concatMacros, "MERGE") == "tupko"
    assert e(concatMacros, "MERGE2(A, B)") == "tupko"
    assert e(concatMacros, "MERGE2(A A, B B)") == "1 tupko 2"
    assert e(concatMacros, "STRINGIZE_MERGE2(A A, B B)") == '"A AB B"'
    # Non-standard MS VC++ behaviour we currently do not emulate.
    if enable_tests_for_unsupported_features:
        assert e(concatMacros, "MERGE2((A), B)") == "(1)2"
        assert e(concatMacros, "MERGE2(A, (B))") == "1(2)"
        assert e(concatMacros, "MERGE2((A), (B))") == "(1)(2)"

    #   Concatenating two hash preprocessor tokens does not produce a valid
    # hash-hash preprocessor token.
    concatMacros = dict(
        A=Macro(None, "1"),
        B=Macro(None, "2"),
        AB=Macro(None, "tupko"),
        MERGE2=Macro(["x", "y"], "x##y"),
        HASH_HASH=Macro(None, "MERGE2(#, #)"),
        QUASI_MERGE2_1=Macro(["x", "y"], "x HASH_HASH y"),
        QUASI_MERGE2_2=Macro(["x", "y"], "MERGE2(x #, # y)"))
    assert e(concatMacros, "MERGE2(A #, # B)") == "1 ## 2"
    assert e(concatMacros, "QUASI_MERGE2_1(A, B)") == "1 ## 2"
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here
    # completely. MS VC++ preprocessor ignores the hash preprocessor operator
    # if processing it is not possible because it is not followed by a
    # function-like macro parameter token. We on the other hand retain it as
    # text.
    #                                                (02.05.2013.) (Jurko)
    assert e(concatMacros, "QUASI_MERGE2_2(A, B)") == '1 #"B"'

    # Concatenating empty preprocessor token sequences.
    concatMacros = dict(
        A=Macro(None, "1"),
        B=Macro(None, "2"),
        AB=Macro(None, "tupko"),
        MERGE4=Macro(["x", "y", "u", "w"], "x y ## u w"))
    assert e(concatMacros, "MERGE4(A, A, B, B)") == "1 tupko 2"
    assert e(concatMacros, "MERGE4(A,  , B, B)") == "1 2 2"
    assert e(concatMacros, "MERGE4(A, A,  , B)") == "1 1 2"
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here which
    # results in "1  2".
    #                                                (02.05.2013.) (Jurko)
    assert e(concatMacros, "MERGE4(A,  ,  , B)") == "1 2"

    #   Hash preprocesor token not treated as the hash preprocessor operator if
    # produced as a result of parameter value substitution or macro expansion.
    macros = dict(
        A=Macro(["x"], "x"),
        HASH=Macro(None, "#"),
        MERGE2_I=Macro(["x", "y"], "x##y"),
        MERGE2=Macro(["x", "y"], "MERGE2_I(x, y)"))
    assert e(macros, "A(#2)") == "#2"
    assert e(macros, "A(HASH 2)") == "# 2"
    assert e(macros, "MERGE2(HASH,2)") == "#2"
    assert e(macros, "A(MERGE2(HASH,2))") == "#2"

    # Arguments in parentheses containing a comma.
    bingoMacros = dict(A=Macro(["x", "y"], "x bingo y"))
    assert e(bingoMacros, "A(1, 2)") == "1 bingo 2"
    assert e(bingoMacros, "A((1), 2)") == "(1) bingo 2"
    assert e(bingoMacros, "A((1, 3), 2)") == "(1, 3) bingo 2"
    assert e(bingoMacros, "A((1, 3), (2, 15, 7, 2))") ==  \
        "(1, 3) bingo (2, 15, 7, 2)"

    # Function & object-like macro call syntax mismatch.
    assert e(dict(AAA=Macro([], "555")), "AAA") == "AAA"
    assert e(dict(AAA=Macro(None, "555")), "AAA()") == "555()"
    assert e(dict(A=Macro(None, "pip")), "A(2)") == "pip(2)"
    assert e(dict(A=Macro(None, "pip"), B=Macro(None, "A(22)")), "B(9)") ==  \
        "pip(22)(9)"

    # Passing function-like macro name as parameter.
    assert e(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x()"), BBB=Macro(["x"], "AAA(x)")), "BBB(B)") == "10"

    # Function-like macro parameters constructed by macro expansion.
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here as it is
    # not compatible with the standard:
    #
    #     #define S 1, 2, 3
    #     #define T3(x, y, z) #x;#y;#z
    #     #define T(x) T3(x)
    #
    #     ------------------------------------------------
    #     call to expand  MS VC++ expansion  our expansion
    #     --------------  -----------------  -------------
    #     T(S)            '"1, 2, 3";;'      '"1";"2";"3"'
    #     ------------------------------------------------
    #
    #   We can add explicit MS VC++-like support for this later on, but only if
    # explicitly needed.
    #                                                (02.05.2013.) (Jurko)
    macros = dict(
        S=Macro(None, "1, 2, 3"),
        T3=Macro(["x", "y", "z"], "#x;#y;#z"),
        T=Macro(["x"], "T3(x)"))
    assert e(macros, "T(S)") == '"1";"2";"3"'

    # More complex function-like parameter substitution tests.
    assert e(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x"), BBB=Macro(["x"], "AAA(x)")), "AAA(B())") == "10"
    assert e(dict(BB=Macro([], "10"), B=Macro([], "5"), AAA=Macro(["x"],
        "B##x"), BBB=Macro(["x"], "AAA(x)")), "BBB(B())") == "B5"

    # Variadic macros.
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here
    # completely. MS VC++ preprocessor expands whitespace in the built-in
    # __VA_ARGS__ variadic macro parameter a bit differently than we do but not
    # in a way we consider significant. The following table illustrates the
    # difference using a macro A defined as '#define A(...) __VA_ARGS__':
    #
    #     --------------------------------------------------
    #     call to expand    MS VC++ expansion  our expansion
    #     --------------    -----------------  -------------
    #     A(1,2,3)          '1,2,3'            '1,2,3'
    #     A(1, 2, 3)        '1, 2, 3'          '1,2,3'
    #     A(   1, 2, 3)     '1, 2, 3'          '1,2,3'
    #     A(1, 2, 3   )     '1, 2, 3'          '1,2,3'
    #     A(1, 2,    3)     '1, 2, 3'          '1,2,3'
    #     A(1, 2   ,    3)  '1, 2 , 3'         '1,2,3'
    #     --------------------------------------------------
    #                                                (02.05.2013.) (Jurko)
    assert e(dict(A=Macro([], "__VA_ARGS__")), "A()") == "__VA_ARGS__"
    assert e(dict(A=Macro([], "__VA_ARGS__")), "A(1, 2, 3)") == "__VA_ARGS__"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A()") == ""
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1,2,3)") == "1,2,3"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1, 2, 3)") == "1,2,3"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(   1, 2, 3)") == "1,2,3"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1, 2, 3   )") == "1,2,3"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1,2,   3)") == "1,2,3"
    assert e(dict(A=Macro(["..."], "__VA_ARGS__")), "A(1,2  ,   3)") == "1,2,3"
    assert e(dict(A=Macro(["x", "..."], "__VA_ARGS__")), "A(1, 2, 3)") == "2,3"
    assert e(dict(A=Macro(["x", "..."], "__VA_ARGS__")), "A(1,  2, 3)") ==  \
        "2,3"
    assert e(dict(A=Macro(["x", "y", "..."], "__VA_ARGS__")), "A(1, 2, 3)")  \
        == "3"
    assert e(dict(A=Macro(["x", "y", "z", "..."], "__VA_ARGS__")),  \
        "A(1, 2, 3)") == ""
    assert e(dict(A=Macro(["x", "y", "z", "..."], "__VA_ARGS__, z, y, x")),
        "A(1, 2, 3)") == ", 3, 2, 1"

    # Variadic macro __VA_ARGS__ parameter treated as a regular parameter.
    macros = stringizeMacros.copy()
    macros.update(
        A1=Macro(["x", "..."], "#x #__VA_ARGS__"),
        A2=Macro(["x", "..."], "S2(x) S2(__VA_ARGS__)"),
        B=Macro(None, "0"))
    assert e(macros, "A1(B, B)") == '"B" "B"'
    assert e(macros, "A2(B, B)") == '"0" "0"'
    # Implementation note:
    #   We do not preserve MS Visual C++ preprocessor behaviour here.
    #
    #     #define A2(x, ...) S2(x) S2(__VA_ARGS__)
    #     #define S2(x) #x
    #
    #     ------------------------------------------------
    #     call to expand  MS VC++ expansion  our expansion
    #     --------------  -----------------  -------------
    #     A2(B,B,B)       '"0" "0,0"'        '"B" "0"'
    #     ------------------------------------------------
    #
    #   These use cases actually run into undefined behaviour (more parameters
    # get passed to function-like macros than have been declared for it) and so
    # anything we do is correct, but on the other hand this case does not seem
    # like something we need to support for our include-tree detection anyway.
    # MS VC++ preprocessor behaviour here is based on more general deviation
    # from the standard where function-like macro invocation parameters are
    # interpreted incorrectly if more than one is a result of a single macro
    # expansion.
    #                                                (02.05.2013.) (Jurko)
    assert e(macros, "A1(B, B, B)") == '"B" "B,B"'
    assert e(macros, "A2(B, B, B)") == '"0" "0"'

    # Invalid number of macro arguments.
    allow_invalid_number_of_arguments = False
    if allow_invalid_number_of_arguments:
        # Implementation note:
        #   In case we wish to match MS Visual C++ preprocessor behavior, we
        # should allow function-like macro expansions with an invalid number of
        # parameters by ignoring extra ones and expanding missing ones as empty
        # strings.
        #                                            (08.05.2013.) (Juraj)
        assert e(dict(A=Macro(["x", "y"], "a;x;y;b")), "A()") == "a;;;b"
        assert e(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(1,)") == "a;1;;b"
        assert e(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(,2)") == "a;;2;b"
        assert e(dict(A=Macro(["x", "y"], "a;x;y;b")), "A(1,2,3)") == "a;1;2;b"
        assert e(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")), "A()")  \
            == "a;;;;b"
        assert e(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
            "A(1)") == "a;1;;;b"
        assert e(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
            "A(,2)") == "a;;2;;b"
        assert e(dict(A=Macro(["x", "y", "..."], "a;x;y;__VA_ARGS__;b")),
            "A(,,,4)") == "a;;;,4;b"

    # Recursive macro expansion.
    assert e(dict(SELF=Macro(None, "SELF")), "SELF") == "SELF"
    assert e(dict(SELF=Macro(None, "X SELF")), "SELF") == "X SELF"
    assert e(dict(SELF=Macro([], "SELF()")), "SELF()") == "SELF()"
    assert e(dict(SELF=Macro([], "X SELF()")), "SELF()") == "X SELF()"
    assert e(dict(A=Macro(None, "B"), B=Macro(None, "A")), "A") == "A"
    assert e(dict(A=Macro(None, "1 B"), B=Macro(None, "2 A")), "A") == "1 2 A"
    assert e(dict(A=Macro(None, "B"), B=Macro(None, "C"), C=Macro(None, "A")),
        "A") == "A"
    assert e(dict(A=Macro(None, "1 B"), B=Macro(None, "2 C"), C=Macro(None,
        "3 A")), "A") == "1 2 3 A"
    assert e(dict(A=Macro(["x"], "B(x)"), B=Macro(["x"], "A(x)")), "A(B(x))"
        ) == "A(B(x))"

if __name__ == '__main__':
    tests()