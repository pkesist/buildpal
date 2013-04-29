from utils import TempFile

import copy
import itertools
import os
import re
import sys
import types
import zipfile

DEFINE = re.compile('^\s*#\s*define\s+(\w+)(.*)$')
INCLUDE = re.compile('^\s*#\s*include\s*(.+?)\s*$')
ID = re.compile('[a-zA-Z_](\w*)')
HASH=re.compile('\A\#(\S+)')
HASHHASH=re.compile('\s*\#\#\s*')
COMMENT=re.compile('(\s*//(.*))|(\s*/\*(.|\n)*?\*/)')

def expand_hash(expr):
    return HASH.sub('"\\1"', HASHHASH.sub('', expr))

def find_potential_macro(expr, offset=0):
    match = ID.search(expr, offset)
    if not match:
        return None
    start = match.start()
    # Do not consider as a macro value if inside quotes.
    # Find number of (unescaped) quotes before this identifier)
    num_quotes=sum(1 for _ in filter(lambda i : expr[i] == '"' and (i==0 or expr[i-1] != '\\'), range(offset, match.start())))
    if num_quotes % 2 == 1:
        return find_potential_macro(expr, match.end())
    return match

class MacroValue:
    def __init__(self, params=None, expr=None):
        self.params = params
        self.expr = expr
        self.variadic = False

    def __eq__(self, other):
        return (self.params == other.params and
            self.expr == other.expr)

    def __hash__(self):
        return (self.params, self.expr).__hash__()

    def parse_def(self, expr):
        if not expr:
            self.params = None
            self.expr = ''
            return
        has_params = expr[0] == '('
        rest = 0
        if has_params:
            while rest < len(expr) and expr[rest] != ')':
                rest += 1
            if rest == len(expr):
                raise Exception("Missing close brace.")
            self.params = list(a.strip() for a in expr[1:rest].split(','))
            if self.params[-1] == '...':
                self.params[-1] = '__VA_ARGS__'
                self.variadic = True
            self.params = tuple(self.params)
        else:
            self.params = None
        self.expr = expr[rest + 1:].strip()

    def subst(self, pp, name, args, debug=False, expanded={}):
        if self.variadic:
            if len(args) < len(self.params) - 1:
                return
        else:
            if len(args) != len(self.params):
                return
        #exp_args = [set(pp.expand(arg, debug=debug, expanded=expanded)) if arg else [''] for arg in args]
        #assert len(exp_args) == len(args)
        #for t in itertools.product(*exp_args):
        t = args
        assert len(t) == len(args)
        val = self.expr
        last = len(self.params)-1
        if self.variadic and len(t) > last:
            t = list(t)
            t[last] = ",".join(t[last:])
            del t[last + 1:]
            assert len(t) == last or len(t) == len(self.params)
        for x in range(len(t)):
            what = t[x]
            val = re.sub(self.params[x], what, val)
        result = expand_hash(val)
        if result:
            expanded_result = set(pp.expand(result, debug=debug, expanded=expanded))
            for x in expanded_result:
                yield x


class Preprocessor:
    def __init__(self):
        self.macros = {}
        self.include_stack = list()
        self.include_path = []
        self.processed = set()
        self.depends = {}

    def add_path(self, path):
        self.include_path.append(path)

    def already_processed(self, file):
        if not file in self.processed:
            return False
        if not file in self.depends:
            #print("Skipping '{}' - no dependencies.".format(file))
            return True
        depends = self.depends[file]
        for macro in depends:
            if not depends[macro].issuperset(self.macros.get(macro, set())):
                return False
        #print("Skipping '{}' - dependencies already expanded.".format(file))
        return True

    def add_macro(self, macro):
        m = macro.split('=')
        assert len(m) == 1 or len(m) == 2
        mac = m[0]
        val = m[1] if len(m) == 2 else None
        self.macros[mac] = {MacroValue(None, val)}
    
    def expand(self, expr, start=True, depth=0, debug=False, expanded={}):
        assert expr
        if 'iter\\reverse1.hpp' in self.current():
            debug = True
        if debug: print("Expanding '{}' - depth {}.".format(expr, depth))

        match = None
        l = 0

        while not match:
            match = find_potential_macro(expr, offset=l)
            if not match:
                yield expr
                return

            name = match.group(0)
            # We must record any potential macro candidates to create a
            # correct dependency tree. It is not enough to record those
            # identifiers which are _currently_ macros. (i.e. in
            # self.macros)
            expanded.setdefault(depth, set()).add(name)
            def skip():
                if not name in self.macros:
                    return True
                return depth > 0 and any([name in expanded[k] for k in range(0, depth)])

            if skip():
                l = match.end(0)
                match = None
                continue

        name = match.group(0)
        begin = match.start(0)
        end = match.end(0)

        values = []
        # Consider the following snippet:
        #
        # #if COND1
        # #define xxx yyy
        # #endif
        #
        # #define HEADER xxx.h
        # #define STR(x) #x
        # #include STR(HEADER)
        #
        #   We have no idea whether 'xxx' is defined or not, so we must consider
        # the case it is undefined. To make things simpler we add an artificial
        # macro value so that it that expands to itself.
        additional = [MacroValue(None, name)]

        for macro_value in itertools.chain(self.macros[name], additional):
            curr_end = end
            if macro_value.params is not None:
                if end == len(expr):
                    continue
                result = self.get_args(expr[end:])
                if result is None: continue
                args, length = result
                if debug: print("Substituting {} {} with {}".format(name, macro_value.params, args))
                curr_end += length
                val = set(macro_value.subst(self, name, args, debug, expanded))
            else:
                val = [expand_hash(macro_value.expr)]

            for v in val:
                if debug: print("Got {}.".format(v))
            if curr_end < len(expr):
                local_expanded = {}
                for d in range(0, depth):
                    local_expanded[d] = expanded[d]
                tail = set(self.expand(expr[end:], False, depth, debug, local_expanded))
                if depth in local_expanded:
                    expanded[depth].update(local_expanded[depth])
            else:
                tail = ['']

            values.extend((expr[:begin] + v + t for t in tail for v in val))
        if start:
            for value in values:
                for v in set(self.expand(value, True, depth + 1, debug, expanded)):
                    #print("Macro expansion depth {}: '{}' expanded to '{}'".format(depth, expr, v))
                    yield v
        else:
            for i in values:
                yield i

    def get_args(self, str):
        i = 0
        while str[i] in (' ', '\t'): i += 1
        if str[i] != '(':
            return None
        nesting = 0
        args = []
        curr_arg = []
        for i in range(i, len(str)):
            c = str[i]
            if c == '(':
                if nesting != 0:
                    curr_arg.append(c)
                nesting += 1
                continue
            elif c == ')':
                nesting -= 1
                if nesting == 0:
                    args.append("".join(curr_arg))
                    break
                curr_arg.append(c)
            elif c == ',' and nesting == 1:
                args.append("".join(curr_arg))
                curr_arg = []
            else:
                curr_arg.append(c)
        return args, i + 1

    @staticmethod
    def is_header(inc):
        return (inc[0] == '"' and inc[-1] == '"') or (inc[0] == '<' and inc[-1] == '>')

    def scan_file_if_exists(self, dir, file, indent, expanded_macros):
        full = os.path.normpath(os.path.join(dir, file))
        if not os.path.isfile(full):
            return
        print("    " * indent + "Scanning {}".format(full))
        yield file, full
        for z in self.scan_file(full, indent + 1, expanded_macros):
            yield z

    def expand_if_needed(self, inc, expanded_macros):
        if self.is_header(inc):
            yield inc
            return
        expanded = {}
        for x in set(x for x in self.expand(inc, True, 0, False, expanded) if self.is_header(x)):
            yield x
        for depth in expanded:
            for macro in expanded[depth]:
                expanded_macros.add(macro)

    def process_include(self, inc, indent, expanded_macros):
        for x in self.expand_if_needed(inc, expanded_macros):
            assert self.is_header(x)
            try:
                if x[0] == '"':
                    for z in self.scan_file_if_exists(os.path.split(self.current())[0], x[1:-1], indent, expanded_macros):
                        yield z
                for inc in self.include_path:
                    for z in self.scan_file_if_exists(inc, x[1:-1], indent, expanded_macros):
                        yield z
            except:
                import traceback
                traceback.print_exc()

    def process_define(self, macro, expr):
        v = MacroValue()
        v.parse_def(expr)
        self.macros.setdefault(macro, set()).add(v)

    def process(self, line, lineno, indent, expanded_macros):
        if 'iter\\reverse1.hpp' in self.current():
            print("We are at '{}':{}".format(self.current(), lineno))
        d = DEFINE.match(line)
        if d: self.process_define(d.group(1), d.group(2))
        m = INCLUDE.match(line)
        if m:
            for x in self.process_include(m.group(1), indent, expanded_macros):
                yield x
        
    def scan_file(self, filename, indent=0, expanded_macros=set()):
        if filename in self.include_stack:
            return
        if self.already_processed(filename):
            return
        self.include_stack.append(filename)
        lineno = 0
        self_sufficient = True
        current_macros = set((macro for macro in self.macros))
        with open(filename, 'rt') as file:
            current_expanded = set()
            curr = ''
            for line in file.readlines():
                lineno += 1
                if len(line) > 2 and line[-2:] == '\\\n':
                    curr += line[:-2] + ' '
                    continue
                else:
                    for a in self.process(COMMENT.sub('', curr + line), lineno, indent, current_expanded):
                        yield a
                    curr = ''
            self.processed.add(filename)
            if current_expanded:
                self.depends[filename]={}
                for macro in current_expanded:
                    self.depends[filename].get(macro, set()).update(self.macros.get(macro, set()))
            expanded_macros.update(current_expanded)
            if current_expanded:
                print("'{}' depends on:".format(filename))
                for x in current_expanded:
                    print("    ", x)
        self.include_stack.pop()

    def current(self):
        assert self.include_stack
        return self.include_stack[-1]

def collect_headers(cpp_file, rel_dir, search_path, defines):
    try:
        preprocessor = Preprocessor()
        for path in search_path:
            preprocessor.add_path(path)
        for macro in defines:
            preprocessor.add_macro(macro)
        zip_file = TempFile(suffix='.zip')
        with zipfile.ZipFile(zip_file.filename(), 'w', zipfile.ZIP_DEFLATED, False) as zip:
            for file, full in preprocessor.scan_file(os.path.join(rel_dir, cpp_file)):
                zip.write(full, file)
        macros = [
        ('BOOST_PP_FILENAME_1', 'BOOST_PP_FILENAME_1'),
        ('BOOST_PP_ARRAY_ELEM', 'BOOST_PP_ARRAY_ELEM(2, BOOST_PP_ITERATION_PARAMS_1)'),
        ('BOOST_PP_ARRAY_ELEM_I', 'BOOST_PP_ARRAY_ELEM_I(2, (3,(0,BOOST_RESULT_OF_NUM_ARGS,<boost/utility/detail/result_of_iterate.hpp>)))'),
        ('BOOST_PP_TUPLE_ELEM', 'BOOST_PP_TUPLE_ELEM(3, 2, (0,16,<boost/utility/detail/result_of_iterate.hpp>))'),
        ('BOOST_PP_TUPLE_ELEM_I_OO', 'BOOST_PP_TUPLE_ELEM_I_OO((3, 2, (0,16,<boost/utility/detail/result_of_iterate.hpp>)))'),
        ('BOOST_PP_TUPLE_ELEM_I', 'BOOST_PP_TUPLE_ELEM_I(3, 2, (0,16,<boost/utility/detail/result_of_iterate.hpp>))'),
        ('BOOST_PP_TUPLE_ELEM_E_3', 'BOOST_PP_TUPLE_ELEM_E_3 (0,16,<boost/utility/detail/result_of_iterate.hpp>)'),
        ('BOOST_PP_TUPLE_ELEM_II', 'BOOST_PP_TUPLE_ELEM_II((2, (0, 16, <boost/utility/detail/result_of_iterate.hpp>, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)))'),
        ('BOOST_PP_TUPLE_ELEM_III_OO', 'BOOST_PP_TUPLE_ELEM_III_OO((2, (0, 16, <boost/utility/detail/result_of_iterate.hpp>, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)))'),
        #('BOOST_PP_ITERATION_PARAMS_1', 'BOOST_PP_ITERATION_PARAMS_1'),
        #('BOOST_PP_TUPLE_ELEM', 'BOOST_PP_TUPLE_ELEM(3, 2, BOOST_PP_ARRAY_DATA(BOOST_PP_ITERATION_PARAMS_1))'),
        ]

        for macro, expr in macros:
        #for macro in ['BOOST_PP_ARRAY_DATA_II']:
            print("MACRO '{}'".format(macro))
            for macro_value in preprocessor.macros[macro]:
                print("-------------------------------------------------------------------")
                print("-------------------------------------------------------------------")
                print("-------------------------------------------------------------------")
                print("Id '{}'".format(id(macro_value)))
                print("Params '{}'".format(macro_value.params))
                print("Expr   '{}'".format(macro_value.expr))
                print("-------------------------------------------------------------------")
                #import pdb
                #pdb.set_trace()
            for x in preprocessor.expand(expr, debug=True):
                print("{} expanded to: '{}'".format(expr, x))
            print("-------------------------------------------------------------------")
        return zip_file
    except:
        import traceback
        traceback.print_exc()
        pass

    # We failed to collect headers.
    return None

if __name__ == '__main__':
    collect_headers('result_of.hpp',
        r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\utility',
        [r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0'],
        [])
