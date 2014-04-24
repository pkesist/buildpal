#! python3
"""pytest based test module for asm_to_inc.py."""
# Ideas:
# * More detailed input data checking.
#   * Report an error if one procedure starts or exits before another exits.
#     Currently only the target procedure is processed this way, while all
#     other procedure start/end declarations are simply ignored.
#   * Report an error when an ENDP instruction is encountered without a prior
#     matching PROC instruction.
# * More detailed output printer testing using invalid input data. Not strictly
#   necessary at the moment since the input data is currently only prepared by
#   our AsmParser class which has already been tested to construct it in the
#   correct format.
#   * invalid code values
#     * empty code list
#     * invalid code element length (other than 2)
#     * code element containing a char other than a hex digit
#   * invalid offset - empty, containing a char other than a hex digit
#   * asm comment without a leading semicolon
#   * code line without asm data
#   * code line without asm args data

import io
import os.path
import re
import sys

import pytest

from asm_to_inc import (
    _CodeArrayPrinter, _open_with_default, _parse_arguments, _parse_asm_code,
    _UndefinedParam, __version__, ParserError)


class TestOpenWithDefault:

    def test_default(self):
        test_content = "some test content\n\nsome more test content"
        test_stream = io.StringIO()
        with _open_with_default(None, "w", test_stream) as f:
            f.write(test_content)
        assert not f.closed
        test_stream.seek(0, io.SEEK_SET)
        assert test_stream.read() == test_content

    def test_name_and_default(self, tmpdir):
        file = tmpdir.join("test.file")
        test_content = "some test content\n\nsome more test content"
        test_stream = io.StringIO()
        with _open_with_default(str(file), "w", test_stream) as f:
            assert file.exists()
            assert not f.closed
            f.write(test_content)
        assert f.closed
        assert file.read() == test_content
        assert test_stream.tell() == 0
        assert not test_stream.read()

    def test_name_only__read(self, tmpdir):
        file = tmpdir.join("test.file")
        test_content = "some test content\n\nsome more test content"
        file.write(test_content)
        with _open_with_default(str(file), "r", None) as f:
            assert not f.closed
            assert f.read() == test_content
        assert f.closed
        assert file.read() == test_content

    def test_name_only__write(self, tmpdir):
        file = tmpdir.join("test.file")
        test_content = "some test content\n\nsome more test content"
        with _open_with_default(str(file), "w", None) as f:
            assert file.exists()
            assert not f.closed
            f.write(test_content)
        assert f.closed
        assert file.read() == test_content


@pytest.mark.parametrize(("parsed_input", "expected"), (
    # no input
    ([], ""),
    # comments
    (["one", "two"], "// one\n// two\n"),
    (["one and a two"], "// one and a two\n"),
    ([" one", "", "two "], "//  one\n// \n// two \n"),
    # code - single line
    ([["offset", ["ab", "cd", "ef"], "inst", "args", "; comment"]],
        "0xab, 0xcd, 0xef  // offset - inst args; comment\n"),
    # code - multiple lines, last code not longest
    ([["offset1", ["ab", "cd", "ef"], "inst1", "args1", "; comment1"],
      ["offset2", ["12", "34"], "inst2", "args2", "; comment2"]],
        "0xab, 0xcd, 0xef,  // offset1 - inst1 args1; comment1\n"
        "0x12, 0x34         // offset2 - inst2 args2; comment2\n"),
    # code - multiple lines, last code longest but not strictly
    ([["offset1", ["ab", "cd", "ef"], "inst1", "args1", "; comment1"],
      ["offset2", ["12", "34", "56"], "inst2", "args2", "; comment2"]],
        "0xab, 0xcd, 0xef,  // offset1 - inst1 args1; comment1\n"
        "0x12, 0x34, 0x56   // offset2 - inst2 args2; comment2\n"),
    # code - multiple lines, last code strictly longest
    ([["offset1", ["ab", "cd"], "inst1", "args1", "; comment1"],
      ["offset2", ["12", "34", "56"], "inst2", "args2", "; comment2"]],
        "0xab, 0xcd,       // offset1 - inst1 args1; comment1\n"
        "0x12, 0x34, 0x56  // offset2 - inst2 args2; comment2\n"),
    # code - non-empty no asm comment
    ([["offset", ["ab", "cd"], "inst", "args"]],
        "0xab, 0xcd  // offset - inst args\n"),
    # code - empty asm args and no asm comment
    ([["offset", ["ab", "cd"], "inst", ""]],
        "0xab, 0xcd  // offset - inst\n"),
    # code - empty asm args and a non-empty asm comment
    ([["offset", ["ab", "cd"], "inst", "", "; comment"]],
        "0xab, 0xcd  // offset - inst ; comment\n"),
    # code - asm comment alignment
    ([["offset", ["ab", "cd"], "inst", "args", "; comment1"],
      ["offset", ["12", "34", "56"], "inst", "loong args", "; comment2"]],
        "0xab, 0xcd,       // offset - inst args; comment1\n"
        "0x12, 0x34, 0x56  // offset - inst loong args; comment2\n"),
    ([["offset", ["12", "34", "56"], "inst", "loong args", "; comment2"],
      ["offset", ["ab", "cd"], "inst", "args", "; comment1"]],
        "0x12, 0x34, 0x56,  // offset - inst loong args; comment2\n"
        "0xab, 0xcd         // offset - inst args; comment1\n"),
    # code - asm args alignment
    ([["offset", ["ab"], "inst", "args", "; comment1"],
      ["offset", ["12", "34"], "loong inst", "loong args", "; comment2"]],
        "0xab,       // offset - inst       args; comment1\n"
        "0x12, 0x34  // offset - loong inst loong args; comment2\n"),
    ([["offset", ["12", "34"], "loong inst", "loong args", "; comment2"],
      ["offset", ["ab"], "inst", "args", "; comment1"]],
        "0x12, 0x34,  // offset - loong inst loong args; comment2\n"
        "0xab         // offset - inst       args; comment1\n"),
    # different offset values
    ([["", ["ab", "cd", "ef"], "inst", "args", "; comment"]],
        "0xab, 0xcd, 0xef  //  - inst args; comment\n"),
    ([["badf00d", ["ab", "cd", "ef"], "inst", "args", "; comment"]],
        "0xab, 0xcd, 0xef  // badf00d - inst args; comment\n"),
    # code and comments
    (["I'm a normal comment.",
      ["offset1", ["ab", "cd"], "inst", "args", "; comment1"],
      ["offset2", ["ef"], "inst", "args", "; comment2"],
      "I'm a hidden comment!",
      "I'm a second hidden comment!",
      ["offset3", ["12", "34", "56"], "inst", "loong args", "; comment3"],
      "I'm a crazy comment.",
      "And I'm a sad little comment."],
        "// I'm a normal comment.\n"
        "0xab, 0xcd,       // offset1 - inst args; comment1\n"
        "0xef,             // offset2 - inst args; comment2\n"
        "// I'm a hidden comment!\n"
        "// I'm a second hidden comment!\n"
        "0x12, 0x34, 0x56  // offset3 - inst loong args; comment3\n"
        "// I'm a crazy comment.\n"
        "// And I'm a sad little comment.\n")))
def test_output(parsed_input, expected):
    output_stream = io.StringIO()
    _CodeArrayPrinter(parsed_input).print_to(output_stream)
    output_stream.seek(0, io.SEEK_SET)
    assert output_stream.read() == expected


class TestParseArguments:

    @pytest.mark.parametrize(
        ("argv", "proc_name", "input_file", "output_file"), (
        (["kuku"], "kuku", None, None),
        (["proc_name=kuku"], "proc_name=kuku", None, None),
        (["pipi", "--input-file", "input"], "pipi", "input", None),
        (["alf", "--input-file=input"], "alf", "input", None),
        (["bet", "--input-file=\"input\""], "bet", "\"input\"", None),
        (["omicron", "--input-file", '"input"'], "omicron", '"input"', None),
        (["proc", "--input-file=file1", "--input-file=file2"],
            "proc", "file2", None),
        (["proc", "--input-file", "file1", "--input-file=file2"],
            "proc", "file2", None),
        (["proc", "--input-file", "file1", "--input-file", "file2"],
            "proc", "file2", None),
        (["lele", "--output-file=output"], "lele", None, "output"),
        (["woopsie", "--input-file=input", "--output-file=output"],
            "woopsie", "input", "output"),
        (["--output-file=output", "--input-file=input", "taruk"],
            "taruk", "input", "output"),
        (["--output-file=output", "--input-file", "input", "taruk"],
            "taruk", "input", "output")))
    def test(self, argv, proc_name, input_file, output_file):
        assert _parse_arguments(argv) == (proc_name, input_file, output_file)

    @pytest.mark.parametrize("argv", (
        [],  # missing func-name
        ["proc", "--invalid-option"],
        ["proc", "--input-file"],  # option without value
        ["proc", "extra-param"],
        ["proc", "--input-file", "file1", "extra-param-after-option"]))
    def test_error(self, argv):
        with pytest.raises(SystemExit) as e:
            _parse_arguments(argv)
        assert e.value.code == 2
        del e  # explicitly break reference cycle

    def test_help(self, capsys):
        expected_progname = os.path.basename(sys.argv[0])
        with pytest.raises(SystemExit) as e:
            _parse_arguments(["--help"])
        assert e.value.code == 0
        del e  # explicitly break reference cycle
        out, err = capsys.readouterr()
        assert err == ""
        initial_paragraph, rest = out.split("\n\n", 1)
        assert re.match("usage:\s*{}\s*"
            "\[-h\]\s*"
            "\[--input-file INPUT_FILE\]\s*"
            "\[--output-file OUTPUT_FILE\]\s*"
            "\[--version\]\s*"
            "proc-name".format(expected_progname), initial_paragraph)
        assert rest == """\
Convert ASM/binary procedure code output by the Microsoft Visual Studio C/C++
compiler to C/C++ character array data.

positional arguments:
  proc-name             procedure name to extract

optional arguments:
  -h, --help            show this help message and exit
  --input-file INPUT_FILE
                        input file (default: stdin)
  --output-file OUTPUT_FILE
                        output file (default: stdout)
  --version             print the program version information and exit
"""

    def test_sys_argv(self, monkeypatch):
        test_func_name = "I intend to live forever. So far, so good."
        monkeypatch.setattr(sys, "argv", [sys.argv[0], test_func_name])
        expected = test_func_name, None, None
        assert _parse_arguments(_UndefinedParam) == expected

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as e:
            _parse_arguments(["--version"])
        assert e.value.code == 0
        del e  # explicitly break reference cycle
        out, err = capsys.readouterr()
        assert err == ""
        assert out == "{}\n".format(__version__)


class TestParseAsm:

    @pytest.mark.parametrize(("proc_name", "input", "expected"), (
        # one single-line code
        ("my_proc", """\
my_proc PROC\t; my_proc
  00000\tc3\t ret\t 0
my_proc ENDP\t; my_proc
""",
            ["my_proc PROC; my_proc",
            ["00000", ["c3"], "ret", "0"],
            "my_proc ENDP; my_proc"]),

        # multiple code lines
        ("my_proc", """\
my_proc PROC\t; my_proc
  00000\tc3\t ret\t 0
  00001\tdf\t rot\t 13
my_proc ENDP\t; my_proc
""",
            ["my_proc PROC; my_proc",
            ["00000", ["c3"], "ret", "0"],
            ["00001", ["df"], "rot", "13"],
            "my_proc ENDP; my_proc"]),

        # proc exit with no end-of-line
        ("my_proc", """\
my_proc PROC\t; my_proc
  00000\tc3\t ret\t 0
my_proc ENDP\t; my_proc""",
            ["my_proc PROC; my_proc",
            ["00000", ["c3"], "ret", "0"],
            "my_proc ENDP; my_proc"]),

        # content before and after proc ignored
        ("my_proc", """\
Ignore this!
my_proc PROC\t; my_proc
  00000\tc3\t ret\t 0
my_proc ENDP\t; my_proc
Ignore that!
""",
            ["my_proc PROC; my_proc",
            ["00000", ["c3"], "ret", "0"],
            "my_proc ENDP; my_proc"]),

        # other procedures ignored
        ("my_proc", """\
Ignore this!
dingle PROC\t; dingle
  00000\tc3\t rot\t 13
dingle ENDP\t; dingle
Ignore that!
my_proc PROC\t; my_proc
  00000\tc3\t ret\t 0
my_proc ENDP\t; my_proc
Ignore this as well!
""",
            ["my_proc PROC; my_proc",
            ["00000", ["c3"], "ret", "0"],
            "my_proc ENDP; my_proc"]),

        # complete code lines
        ("my_proc", """\
my_proc PROC\t; my_proc
  00000\tb8 2a 00 00 ff fe\t mov\t eax, 42\t; 2aH
  00006\tff ff\t buga-wuga\t uf, if, of\t; pero
my_proc ENDP\t; my_proc
""",
            ["my_proc PROC; my_proc",
            ["00000", ["b8", "2a", "00", "00", "ff", "fe"], "mov", "eax, 42",
                "; 2aH"],
            ["00006", ["ff", "ff"], "buga-wuga", "uf, if, of", "; pero"],
            "my_proc ENDP; my_proc"]),

        # partial code lines
        ("my_proc", """\
my_proc PROC\t; my_proc
  00000\tb8 2a 00
\t00 ff
\tfe\t mov\t eax, 42\t; 2aH
  00006\tff ff\t buga-wuga\t uf, if, of\t; pero
my_proc ENDP\t; my_proc
""",
            ["my_proc PROC; my_proc",
            ["00000", ["b8", "2a", "00", "00", "ff", "fe"], "mov", "eax, 42",
                "; 2aH"],
            ["00006", ["ff", "ff"], "buga-wuga", "uf, if, of", "; pero"],
            "my_proc ENDP; my_proc"]),

        # non-code lines inside a proc
        ("my_proc", """\
my_proc PROC\t; my_proc
; rumpelstiltskin
  00000\tb8 2a 00 00 ff fe\t mov\t eax, 42\t; 2aH
    gefufna!\tThat's it!  GEFUFNA!!!
  00006\tff ff\t buga-wuga\t uf, if, of\t; pero
einer funfer
my_proc ENDP\t; my_proc
""",
            ["my_proc PROC; my_proc",
            "; rumpelstiltskin",
            ["00000", ["b8", "2a", "00", "00", "ff", "fe"], "mov", "eax, 42",
                "; 2aH"],
            "    gefufna!\tThat's it!  GEFUFNA!!!",
            ["00006", ["ff", "ff"], "buga-wuga", "uf, if, of", "; pero"],
            "einer funfer",
            "my_proc ENDP; my_proc"]),

        # decorated procedure names
        ("my_proc", """\
rufimy_proc??fu@fi PROC\t; my_proc
  00000\tb8 2a 00 00 ff fe\t mov\t eax, 42\t; 2aH
  00006\tff ff\t buga-wuga\t uf, if, of\t; pero
rufimy_proc??fu@fi ENDP\t; my_proc
""",
            ["rufimy_proc??fu@fi PROC; my_proc",
            ["00000", ["b8", "2a", "00", "00", "ff", "fe"], "mov", "eax, 42",
                "; 2aH"],
            ["00006", ["ff", "ff"], "buga-wuga", "uf, if, of", "; pero"],
            "rufimy_proc??fu@fi ENDP; my_proc"])))
    def test_parse_asm_code(self, proc_name, input, expected):
        input_stream = io.StringIO(input)
        parsed = _parse_asm_code(input_stream, proc_name)
        assert parsed == expected

    @pytest.mark.parametrize("multi_line", (False, True))
    @pytest.mark.parametrize(("asm", "expected"), (
        ("\t inst\t args\t; comment", ["inst", "args", "; comment"]),
        ("\t inst\t args; comment", ["inst", "args; comment"]),
        ("\t inst\t args\t;", ["inst", "args", ";"]),
        ("\t inst\t args\t\t\t\t\t; comment", ["inst", "args", "; comment"]),
        ("\t inst\t\t args\t\t\t\t\t; comment", ["inst", "args", "; comment"]),
        ("\t\t inst\t args\t\t\t; comment", ["inst", "args", "; comment"]),
        ("\t inst\t args\t;; comment", ["inst", "args", ";; comment"]),
        ("\t inst\t args\t;  comment", ["inst", "args", ";  comment"]),
        ("\t inst\t args\t; multi word", ["inst", "args", "; multi word"]),
        ("\t inst\t args", ["inst", "args"]),
        ("\t inst\t a, b,  c\t; comment", ["inst", "a, b,  c", "; comment"])))
    def test_asm_parsing(self, multi_line, asm, expected):
        proc_name = "my_proc"
        line_splitter = "\n\t" if multi_line else " "
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  00000\tb8 2a 00{1}00 00 ff fe{2}
{0} ENDP\t; {0}
""".format(proc_name, line_splitter, asm))
        parsed = _parse_asm_code(input_stream, proc_name)
        assert parsed == [
            "{0} PROC; {0}".format(proc_name),
            ["00000", ["b8", "2a", "00", "00", "00", "ff", "fe"]] + expected,
            "{0} ENDP; {0}".format(proc_name)]

    @pytest.mark.parametrize("multi_line", (False, True))
    @pytest.mark.parametrize("asm", (
        # bad field separators
        "\t inst\t args\t",
        "\t inst\t args\t: comment",
        "\t inst\t args\t ; comment",
        "\t inst\t args\tcomment",
        "\t inst \t args\t; comment",
        # missing fields
        "\t",
        "\t ",
        "\t inst",
        "\t inst\t",
        # multi-words asm instruction
        "\t one two\t aaa"))
    def test_asm_parsing__error(self, multi_line, asm):
        proc_name = "my_proc"
        line_splitter = "\n\t" if multi_line else " "
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  00000\tb8 2a 00{1}00 00 ff fe{2}
{0} ENDP\t; {0}
""".format(proc_name, line_splitter, asm))
        expected_error_line_number = 3 if multi_line else 2
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "could not parse code line comment"
        assert e.value.line_number == expected_error_line_number
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize(
        ("expected_error_line", "expected_error_message", "input"), (
        # comment when code line continuation expected
        (3, "incomplete code line", """\
{0} PROC\t; {0}
  00000\tb8 2a 00
badly placed comment line
{0} ENDP\t; {0}
"""),
        # proc exit when code line continuation expected
        (3, "incomplete code line", """\
{0} PROC\t; {0}
  00000\tb8 2a 00
{0} ENDP\t; {0}
"""),
        # file end when code line continuation expected - without newline
        (2, "procedure incomplete", """\
{0} PROC\t; {0}
  00000\tb8 2a 00"""),
        # file end when code line continuation expected - with newline
        (2, "procedure incomplete", """\
{0} PROC\t; {0}
  00000\tb8 2a 00
"""),
        # file end when code line continuation expected - with extra newline
        (3, "incomplete code line", """\
{0} PROC\t; {0}
  00000\tb8 2a 00

""")))
    def test_broken_code_line_continuation(self, expected_error_line,
            expected_error_message, input):
        proc_name = "my_proc"
        input_stream = io.StringIO(input.format(proc_name))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == expected_error_message
        assert e.value.line_number == expected_error_line
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize(("code_line", "next_offset"), (
        # after single-line code
        ("00000\t11 22 33\t inst\t args", "00003"),
        ("0000f\t11 22 33 44 55 66\t inst\t args", "00015"),
        # after multi-line code line followed by bad offset
        ("00000\t11 22\n\t33\t inst\t args", "00003"),
        ("cabae\t11 22\n\t33\t inst\t args", "cabb1"),
        # larger offset
        ("abcabcacc\t11 22 33\t inst\t args", "abcabcacf")))
    def test_code_offset(self, code_line, next_offset):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  {1}
  {2}\tff\t inst\t args
{0} ENDP\t; {0}
""".format(proc_name, code_line, next_offset))
        _parse_asm_code(input_stream, proc_name)

    @pytest.mark.parametrize(("code_line_1", "code_line_2"), (
        # complete code lines
        ("00000\t11 22 33\t inst\t args", "00002\tff\t inst\t args"),
        ("00000\t11 22 33\t inst\t args", "00004\tff\t inst\t args"),
        # partial code line with bad offset
        ("00000\t11 22 33\t inst\t args", "00002\tff"),
        ("00000\t11 22 33\t inst\t args", "00004\tff"),
        # multi-line code line followed by bad offset
        ("00000\t11 22\n\t33\t inst\t args", "00002\tff"),
        ("00000\t11 22\n\t33\t inst\t args", "00004\tff"),
        # larger offset
        ("abcabcacc\t11 22 33\t inst\t args", "abcabcace\tff\t inst\t args"),
        ("abcabcacc\t11 22 33\t inst\t args", "abcabcad0\tff\t inst\t args")))
    def test_code_offset__bad(self, code_line_1, code_line_2):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  {1}
  {2}
{0} ENDP\t; {0}
""".format(proc_name, code_line_1, code_line_2))
        expected_error_line_number = 3 + code_line_1.count("\n")
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "bad code offset"
        assert e.value.line_number == expected_error_line_number
        del e  # explicitly break reference cycle

    def test_code_offset_after_comment(self):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  00100\t11 22 33 44 55 66 77 88 99 aa\t inst\t args
a commento!
  0010a\tff\t inst\t args
{0} ENDP\t; {0}
""".format(proc_name))
        _parse_asm_code(input_stream, proc_name)

    def test_code_offset_after_comment__bad(self):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  00100\t11 22 33 44 55 66 77 88 99 aa\t inst\t args
a commento!
  0010b\tff\t inst\t args
{0} ENDP\t; {0}
""".format(proc_name))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "bad code offset"
        assert e.value.line_number == 4
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize("input", (
        # extra space before asm part
        "  00000\tb8 2a 00 00 00 ff fe \t inst\t args\t; comment",
        # bad offset
        "  \tb8 2a 00 00 00 ff fe",
        "  offset\tb8 2a 00 00 00 ff fe",
        # bad code line start
        "00000\tb8 2a 00 00 00 ff fe",
        " 00000\tb8 2a 00 00 00 ff fe",
        "/t00000\tb8 2a 00 00 00 ff fe",
        # missing code bytes
        "  00000",
        "  00000\t",
        "  00000\t\t inst\t args"))
    def test_comment_looking_like_code(self, input):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
{1}
  00000\taa\t inst\t args
{0} ENDP\t; {0}
""".format(proc_name, input))
        parsed = _parse_asm_code(input_stream, proc_name)
        assert parsed == [
            "{0} PROC; {0}".format(proc_name),
            input,
            ["00000", ["aa"], "inst", "args"],
            "{0} ENDP; {0}".format(proc_name)]

    def test_decorated_proc_name_mismatch(self):
        proc_name = "my_proc"
        input_stream = io.StringIO("""\
??1287fafa{0}lo@@lo! PROC\t; {0}
  00100\t11 22 33 44 55 66 77 88 99 aa\t inst\t args
  0010a\tff\t inst\t args
--1287fafa{0}lo@@lo! ENDP\t; {0}
""".format(proc_name))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "decorated PROC/ENDP proc name mismatch"
        assert e.value.line_number == 4
        del e  # explicitly break reference cycle

    def test_empty_input(self):
        input_stream = io.StringIO("")
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, "proc_name")
        assert str(e.value) == "missing procedure"
        assert e.value.line_number == 0
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize(("expected_error_line", "input"), (
        # proc starts after previous ends
        (5, """\
{0} PROC\t; {0}
  00000\tb8 2a 00 00 00\t mov\t eax, 42\t; 0000002aH
  00005\tc3\t ret\t 0
{0} ENDP\t; {0}
{0} PROC\t; {0}
  00000\tb8 2a 00 00 00\t mov\t eax, 42\t; 0000002aH
  00005\tc3\t ret\t 0
{0} ENDP\t; {0}
"""),
        # proc starts before previous ends
        (3, """\
{0} PROC\t; {0}
  00000\tc3\t ret\t 0
{0} PROC\t; {0}
  00000\tc3\t ret\t 0
{0} ENDP\t; {0}
""")))
    def test_multiple_procedure_start(self, expected_error_line, input):
        proc_name = "my_proc"
        input_stream = io.StringIO(input.format(proc_name))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "multiple procedure start"
        assert e.value.line_number == expected_error_line
        del e  # explicitly break reference cycle

    def test_no_proc_code(self):
        proc_name = "mandula"
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
humpty-dumpty hang by a hose
humpty-dumpty had a flat nose
{0} ENDP\t; {0}
""".format(proc_name))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "missing procedure code"
        assert e.value.line_number == 4
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize(("proc_name", "proc_end"), (
        # missing procedure end line
        ("my_proc", ""),
        ("my_proc", "howlie-howlie"),
        # bad ENDP line - incorrect procedure name
        ("my_proc", "spiffy ENDP\t; spiffy"),
        # bad ENDP line - decorated name errors
        ("my_proc", " my_proc ENDP\t; my_proc"),  # extra space at front
        ("my_proc", "\tmy_proc ENDP\t; my_proc"),  # extra tab at front
        ("my_proc", "my-proc ENDP\t; my_proc"),  # name typo
        ("my_proc", "my proc ENDP\t; my_proc"),  # name typo
        # bad ENDP line - ENDP command errors
        ("my_proc", "my_procENDP\t; my_proc"),
        ("my_proc", "my_proc  ENDP\t; my_proc"),
        ("my_proc", "my_proc\tENDP\t; my_proc"),
        ("my_proc", "my_proc\t ENDP\t; my_proc"),
        ("my_proc", "my_proc \tENDP\t; my_proc"),
        ("my_proc", "my_proc END\t; my_proc"),
        ("my_proc", "my_proc \t; my_proc"),
        ("my_proc", "my_proc\t ; my_proc"),
        ("my_proc", "my_proc\t; my_proc"),
        # bad ENDP line - decorated name & comment separation errors
        ("my_proc", "my_proc ENDP; my_proc"),  # missing tabs
        ("my_proc", "my_proc ENDP\t my_proc"),  # missing semicolon
        ("my_proc", "my_proc ENDP my_proc"),  # missing tabs & semicolon
        ("my_proc", "my_proc ENDP\tmy_proc"),  # missing semicolon & space
        ("my_proc", "my_proc ENDP ; my_proc"),  # space instead of tab
        ("my_proc", "my_proc ENDP \t; my_proc"),  # space instead of tab
        ("my_proc", "my_proc ENDP\t ; my_proc"),  # space instead of tab
        ("my_proc", "my_proc ENDP\t;\tmy_proc"),  # tab instead of space
        ("my_proc", "my_proc ENDP\t;; my_proc"),  # double semicolon
        ("my_proc", "my_proc ENDP\t: my_proc"),  # colon instead of semicolon
        # bad ENDP line - comment errors
        ("my_proc", "my_proc ENDP\t"),  # missing
        ("my_proc", "my_proc ENDP\t; bad proc name"),  # bad proc name
        ("my_proc", "my_proc ENDP\t;my_proc"),  # missing space
        ("my_proc", "my_proc ENDP\t;\tmy_proc"),  # tab instead of space
        ("my_proc", "my_proc ENDP\t;  my_proc"),  # extra leading space
        ("my_proc", "my_proc ENDP\t; my_proc ")))  # extra trailing space
    def test_no_proc_end(self, proc_name, proc_end):
        input_stream = io.StringIO("""\
{0} PROC\t; {0}
  00005\tc3\t ret\t 0
{1}
""".format(proc_name, proc_end))
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "procedure incomplete"
        assert e.value.line_number == 3
        del e  # explicitly break reference cycle

    @pytest.mark.parametrize(("proc_name", "proc_start"), (
        # missing procedure start line
        ("proc_name", ""),
        ("proc_name", "hamburger"),
        # bad PROC line - incorrect procedure name
        ("proc_name", "alfa PROC\t; alfa"),
        # bad PROC line - decorated name errors
        ("proc_name", " proc_name PROC\t; proc_name"),  # extra space at front
        ("proc_name", "\tproc_name PROC\t; proc_name"),  # extra tab at front
        ("proc_name", "proc-name PROC\t; proc_name"),  # name typo
        ("proc_name", "proc name PROC\t; proc_name"),  # name typo
        # bad PROC line - PROC command errors
        ("proc_name", "proc_namePROC\t; proc_name"),
        ("proc_name", "proc_name  PROC\t; proc_name"),
        ("proc_name", "proc_name\tPROC\t; proc_name"),
        ("proc_name", "proc_name\t PROC\t; proc_name"),
        ("proc_name", "proc_name \tPROC\t; proc_name"),
        ("proc_name", "proc_name PRC\t; proc_name"),
        ("proc_name", "proc_name \t; proc_name"),
        ("proc_name", "proc_name\t ; proc_name"),
        ("proc_name", "proc_name\t; proc_name"),
        # bad PROC line - decorated name & comment separation errors
        ("my_proc", "my_proc PROC; my_proc"),  # missing tabs
        ("my_proc", "my_proc PROC\t my_proc"),  # missing semicolon
        ("my_proc", "my_proc PROC my_proc"),  # missing tabs & semicolon
        ("my_proc", "my_proc PROC\tmy_proc"),  # missing semicolon & space
        ("my_proc", "my_proc PROC ; my_proc"),  # space instead of tab
        ("my_proc", "my_proc PROC \t; my_proc"),  # space instead of tab
        ("my_proc", "my_proc PROC\t ; my_proc"),  # space instead of tab
        ("my_proc", "my_proc PROC\t;\tmy_proc"),  # tab instead of space
        ("my_proc", "my_proc PROC\t;; my_proc"),  # double semicolon
        ("my_proc", "my_proc PROC\t: my_proc"),  # colon instead of semicolon
        # bad PROC line - comment errors
        ("proc_name", "proc_name PROC\t"),  # missing
        ("proc_name", "proc_name PROC\t; bad proc name"),  # bad proc name
        ("proc_name", "proc_name PROC\t;proc_name"),  # missing space
        ("proc_name", "proc_name PROC\t;\tproc_name"),  # tab instead of space
        ("proc_name", "proc_name PROC\t;  proc_name"),  # extra leading space
        ("proc_name", "proc_name PROC\t; proc_name ")))  # extra trailing space
    def test_no_proc_start(self, proc_name, proc_start):
        input_stream = io.StringIO(proc_start + "\n")
        with pytest.raises(ParserError) as e:
            _parse_asm_code(input_stream, proc_name)
        assert str(e.value) == "missing procedure"
        assert e.value.line_number == 1
        del e  # explicitly break reference cycle
