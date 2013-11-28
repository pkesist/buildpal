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
                .format(self.make_args()))

        def make_args(self):
            opt = "{}{}{}".format(
                self.esc or (self.option.def_esc() if self.option else ''),
                self.option.name() if self.option else '',
                self.suf or '')
            val = self.val or ''

            if self.sep == ' ':
                return [opt, val]
            else:
                return [opt + (self.sep if self.sep else '') + val]

    def __init__(self, name, suff=None, has_arg=True, separate_arg_with_space=True):
        self.__name = name
        self.__has_arg = has_arg
        self.__separate_arg_with_space = separate_arg_with_space
        self.__def_sep = '' if not self.__has_arg or not separate_arg_with_space else ' '

        val_regex = "(?P<suf>{})?{}$".format(
            re.escape(suff if suff else ''),
            r"(?P<val>.+)?" if self.__has_arg else '')
        self.__option_regex = re.compile(r"{name}{end}".format(
            name=re.escape(self.__name), end=val_regex))

    def name(self):
        return self.__name
        
    def set_esc(self, esc):
        self.esc = esc

    def def_esc(self):
        return self.esc[0]

    def __make_match(self, esc, suf, sep, val):
        return CmdLineOption.Value(self, esc, suf, sep, val)

    def make_value(self, val=None):
        return CmdLineOption.Value(self, self.def_esc(), '', self.__def_sep, val)

    def parse(self, option, iter):
        if option[0] not in self.esc:
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

        if self.__separate_arg_with_space:
            try:
                x = next(iter)
                return self.__make_match(esc, suf, ' ', x)
            except StopIteration:
                # Fall through to exception below
                pass 

        raise RuntimeError("Missing value for option '{}'.".format(option))

class FreeOption:
    @classmethod
    def name(cls):
        return ''

    class Value:
        def __init__(self, str):
            self.str = str
            self.option = FreeOption()
        
        def make_args(self):
            return [self.str]
        
class CmdLineOptions:
    __options = {}

    def __init__(self, esc):
        if esc is None:
            raise RuntimeError("Command line option must have escape sequence defined.")
        if isinstance(esc, str):
            esc = [esc]
        if not isinstance(esc, list):
            raise RuntimeError("Escape sequence parameter must be a string or list of strings.")
        self.esc = esc

    def add_option(self, option):
        option.esc = self.esc
        self.__options[option.name()] = option

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
                if token[0] not in self.esc:
                    result.append(self.__free_option(token))
                    continue

                found = False
                option_found = token[1:]
                while option_found and option_found not in self.__options:
                    option_found = option_found[:-1]
                assert option_found
                option = self.__options[option_found]
                match = option.parse(token, tokenIter)
                assert match
                result.append(match)
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
        return FreeOption.Value(token)
        

class Category: pass
class BuildLocalCategory(Category): pass
class PCHCategory(Category): pass
class PreprocessingCategory(Category): pass
class CompilationCategory(Category): pass
class LinkingCategory(Category): pass
class SpecialHandlingCategory(Category): pass

class CompilerOption(CmdLineOption):
    def __init__(self, name, suff=None, has_arg=True, separate_arg_with_space=True):
        super().__init__(name, suff, has_arg, separate_arg_with_space)
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

