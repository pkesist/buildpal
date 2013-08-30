import os
import re
import shlex

class CmdLineOption:
    class Value:
        def __init__(self, option, esc, suf, sep, val):
            self.option = option
            self.esc = esc
            self.sep = sep
            self.suf = suf
            self.val = val

        def __str__(self):
            return ("<CmdLineOption.Value object: '{}'>"
                .format(self.make_str()))

        def make_str(self):
            return "{}{}{}{}{}".format(
                self.esc or (self.option.esc() if self.option else ''),
                self.option.name() if self.option else '',
                self.suf or '',
                self.sep or '',
                self.val or '')

    def __init__(self, name, esc, suff=None, has_arg=True, allow_spaces=True):
        self.__name = name
        self.__has_arg = has_arg
        self.__allow_spaces = allow_spaces
        if esc is None:
            raise RuntimeError("Command line option must have escape sequence defined.")
        if isinstance(esc, str):
            esc = [esc]
        if not isinstance(esc, list):
            raise RuntimeError("Escape sequence parameter must be a string or list of strings.")
        self.__esc = esc
        self.__def_sep = '' if not self.__has_arg or not allow_spaces else ' '

        val_regex = "(?P<suf>{})?{}$".format(
            re.escape(suff if suff else ''),
            r"(?P<val>.+)?" if self.__has_arg else '')
        self.__option_regex = re.compile(r"{name}{end}".format(
            name=re.escape(self.__name), end=val_regex))

    def name(self):
        return self.__name
        
    def esc(self):
        return self.__esc[0]

    def __make_match(self, esc, suf, sep, val):
        return CmdLineOption.Value(self, esc, suf, sep, val)

    def make_value(self, val=None):
        return CmdLineOption.Value(self, self.esc(), '', self.__def_sep, val)

    def parse(self, option, iter):
        if option[0] not in self.__esc:
            return None
        esc = option[0]
        match = self.__option_regex.match(option[1:])
        if not match:
            return None
        suf = match.group('suf')
        if not self.__has_arg:
            return self.__make_match(esc, suf, None, None)

        val = match.group('val')
        if val is not None:
            return self.__make_match(esc, suf, '', val)

        if self.__allow_spaces:
            try:
                x = next(iter)
                return self.__make_match(esc, suf, ' ', x)
            except StopIteration:
                # Fall through to exception below
                pass 

        raise RuntimeError("Missing value for option '{}'.".format(option))

class FreeOption:
    def name(self): return ''
    def esc(self): return ''
        
class CmdLineOptions:
    __options = []

    def add_option(self, option):
        self.__options.append(option)

    def parse_options(self, cwd, options):
        result = []
        tokenIter = iter(options)
        while True:
            try:
                token = next(tokenIter)
                if token[0] == '@':
                    # Found a response file - read contents and parse it
                    # recursively.
                    options = None
                    with open(os.path.join(cwd, token[1:]), 'rt') as responseFile:
                        options = shlex.split(" ".join(responseFile.readlines()))
                    result.extend(self.parse_options(cwd, options))
                    continue
                found = False
                for option in self.__options:
                    match = option.parse(token, tokenIter)
                    if match:
                        found = True
                        result.append(match)
                        break
                if not found:
                    result.append(self.__free_option(token))
            except StopIteration:
                break
        return result

    def get_options(self, command, cwd, types):
        if isinstance(types, type):
            types = [types]
        for token in self.parse_options(cwd, command):
            if type(token.option) in types:
                yield token

    def __free_option(self, token):
        return CmdLineOption.Value(FreeOption(), None, None, None, token)
        

class Category: pass
class BuildLocalCategory(Category): pass
class PCHCategory(Category): pass
class PreprocessingCategory(Category): pass
class CompilationCategory(Category): pass
class LinkingCategory(Category): pass

class CompilerOption(CmdLineOption):
    def __init__(self, name, esc, suff=None, has_arg=True, allow_spaces=True):
        super().__init__(name, esc, suff, has_arg, allow_spaces)
        self.__categories = set()
        self.__macros = set()

    def add_category(self, cat):
        self.__categories.add(cat)
        
    def test_category(self, cat):
        return cat in self.__categories

    def add_macro(self, macro):
        self.__macros.add(macro)

    def get_macros(self, value):
        result = []
        for macro in self.__macros:
            if callable(macro):
                t = macro(value)
                if t:
                    result.append(t)
            else:
                result.append(macro)
        return result

