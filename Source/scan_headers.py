#! python3
from utils import TempFile
from preprocessor import Macro, expand_complex

import copy
import itertools
import os
import re
import sys
import types
import zipfile
DEFINE = re.compile('^\s*#\s*define\s+(\w+)(.*)$')
INCLUDE = re.compile('^\s*#\s*include\s*(.+?)\s*$')
COMMENT=re.compile('(\s*//(.*))|(\s*/\*(.|\n)*?\*/)')

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
        expanded = set()
        for x in set(x for x in expand_complex(self.macros, inc, expanded) if self.is_header(x)):
            yield x
        expanded_macros.update(expanded)

    def process_include(self, inc, indent, expanded_macros):
        for x in self.expand_if_needed(inc, expanded_macros):
            assert self.is_header(x)
            if x[0] == '"':
                for z in self.scan_file_if_exists(os.path.split(self.current())[0], x[1:-1], indent, expanded_macros):
                    yield z
            for inc in self.include_path:
                for z in self.scan_file_if_exists(inc, x[1:-1], indent, expanded_macros):
                    yield z

    def process_define(self, macro, expr):
        if not expr:
            params = None
            expr = None
        else:
            has_params = expr[0] == '('
            rest = 0
            if has_params:
                while rest < len(expr) and expr[rest] != ')':
                    rest += 1
                if rest == len(expr):
                    raise Exception("Missing close brace.")
                params = list(a.strip() for a in expr[1:rest].split(','))
                if len(params) == 1 and params[0] == '':
                    params = []
            else:
                params = None
            expr = expr[rest + 1:].strip()
        v = Macro(params, expr)
        self.macros.setdefault(macro, set()).add(v)

    def process(self, line, lineno, indent, expanded_macros):
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
        return zip_file
    except:
        import traceback
        traceback.print_exc()

    # We failed to collect headers.
    return None

if __name__ == '__main__':
    #collect_headers('result_of.hpp',
    #    r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0\boost\utility',
    #    [r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0'],
    #    [])
    collect_headers('gaga.cpp',
        r'D:\Sandboxes\PKE\DistriBuild\Source',
        [r'D:\Sandboxes\PKE\Libraries\Boost\boost_1_53_0'],
        [])
