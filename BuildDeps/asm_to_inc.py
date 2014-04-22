#! python3

import contextlib
import re
import sys

from argparse import ArgumentParser


__version__ = "1.0.dev0"


class ParserError(Exception):
    def __init__(self, msg, line_number):
        Exception.__init__(self, msg)
        self.line_number = line_number


class _UndefinedParam:
    pass


def _parse_arguments(argv):
    parser = ArgumentParser(description="Convert ASM/binary procedure code "
        "output by the Microsoft Visual Studio C/C++ compiler to C/C++ "
        "character array data.")
    parser.add_argument("proc_name", metavar="proc-name", help="procedure "
        "name to extract")
    parser.add_argument("--input-file", help="input file (default: stdin)")
    parser.add_argument("--output-file", help="output file (default: stdout)")
    parser.add_argument("--version", action="version",
        version="%(prog)s " + __version__,
        help="print the program version information and exit")
    if argv is _UndefinedParam:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    return args.proc_name, args.input_file, args.output_file


@contextlib.contextmanager
def _open_with_default(name, mode, default):
    """
    Context manager for opening a given file or using a preopened one.

    If the file name is specified as None, a preopened default file is returned
    instead of opening a new one. The preopened file, if used, will not be
    closed on exit.

    """
    need_close = False
    try:
        if name is None:
            file = default
        else:
            file = open(name, mode)
            need_close = True
        yield file
    finally:
        if need_close:
            file.close()


def main(argv=_UndefinedParam):
    proc_name, input_file, output_file = _parse_arguments(argv)
    try:
        with _open_with_default(input_file, "r", sys.stdin) as f_in:
            with _open_with_default(output_file, "w", sys.stdout) as f_out:
                convert_to_c_array(f_in, f_out, proc_name)
    except ParserError as e:
        print("ERROR: line {} - {}".format(e.line_number, e))
        return -2


def convert_to_c_array(input_stream, output_stream, proc_name):
    output_lines = _parse_asm_code(input_stream, proc_name)
    _output_c_array(output_stream, output_lines)


_rs_code_line_partial = "\t([0-9a-fA-F]{2}(?: [0-9a-fA-F]{2})*)(?:\t+ (.*))?$"
_re_code_line = re.compile("  ([0-9a-fA-F]+){}".format(_rs_code_line_partial))
_re_code_line_partial = re.compile(_rs_code_line_partial)
_re_asm_code_and_comment = re.compile("(\S+)\t*(?: ([^\t]*))(?:\t*(;.*))?$")


def _parse_code_line(line_number, line, partial_code):
    if partial_code:
        # code line continuation expected
        match = _re_code_line_partial.match(line)
        if not match:
            raise ParserError("incomplete code line", line_number)
        offset = partial_code[0]
        binary_code = partial_code[1] + " " + match.group(1)
        asm_code_and_comment = match.group(2)
    else:
        # new code line or comment expected
        match = _re_code_line.match(line)
        if not match:
            return line  # comment
        offset = match.group(1)
        binary_code = match.group(2)
        asm_code_and_comment = match.group(3)

    result = [offset, binary_code]
    if not asm_code_and_comment:
        return result  # incomplete code line

    match = _re_asm_code_and_comment.match(asm_code_and_comment)
    if not match:
        raise ParserError("could not parse code line comment", line_number)
    result.append(match.group(1))  # instruction
    result.append(match.group(2))  # params
    comment = match.group(3)
    if comment:
        result.append(comment)
    return result  # complete code line


def _parse_asm_code(input_stream, proc_name):
    STATE_NOT_COLLECTING = 0
    STATE_COLLECTING = 1
    STATE_COLLECTED = 2

    decorated = "\S*{}\S*".format(proc_name)
    re_proc_start = re.compile("({} PROC)\t+(; {})$".format(decorated, proc_name))
    re_proc_end = re.compile("({} ENDP)\t+(; {})$".format(decorated, proc_name))

    output = []
    partial_code = None
    has_code = False

    state = STATE_NOT_COLLECTING
    for n, line in enumerate(input_stream, 1):
        if line[-1] == "\n":
            line = line[:-1]

        match_proc_start = re_proc_start.match(line)
        if match_proc_start:
            if state != STATE_NOT_COLLECTING:
                raise ParserError("multiple procedure start", n)
            state = STATE_COLLECTING
            assert partial_code is None
            output.append("".join(match_proc_start.group(1, 2)))
            continue

        match_proc_end = re_proc_end.match(line)
        if match_proc_end:
            if state != STATE_COLLECTING:
                raise ParserError("unexpected ENDP", n)
            state = STATE_COLLECTED
            assert partial_code is None
            output.append("".join(match_proc_end.group(1, 2)))
            continue

        if state != STATE_COLLECTING:
            continue

        parsed_line = _parse_code_line(n, line, partial_code)
        if isinstance(parsed_line, str):
            assert partial_code is None
            output.append(line)
        elif len(parsed_line) < 3:
            partial_code = parsed_line
        else:
            has_code = True
            partial_code = None
            output.append(parsed_line)

    if state == STATE_NOT_COLLECTING:
        raise ParserError("missing procedure", n)
    if state != STATE_COLLECTED:
        raise ParserError("procedure incomplete", n)
    if not has_code:
        raise ParserError("missing procedure code", n)
    return output


def _output_c_array(output_stream, output):
    #TODO: too long - refactor
    max_code_len = 0
    max_code_count = 0
    max_asm_inst_len = 0
    for i, x in enumerate(output):
        if not isinstance(x, str):
            code_len = len(x[1])
            if code_len == max_code_len:
                max_code_count += 1
            elif code_len > max_code_len:
                max_code_count = 1
                max_code_len = code_len
            last_code_line = i
            asm_inst = x[2]
            if len(asm_inst) > max_asm_inst_len:
               max_asm_inst_len = len(asm_inst)
    last_code_len = output[last_code_line][1]
    last_code_longest = last_code_len == max_code_len
    last_code_strictly_longest = max_code_count == 1 and last_code_longest

    for i, x in enumerate(output):
        if isinstance(x, str):
            print("// {}".format(x), file=output_stream)
        else:
            offset, code, asm_inst, asm_params, *asm_comment = x
            line = _c_array_code_line(offset, code, asm_inst, asm_params,
                asm_comment[0] if asm_comment else "", max_code_len,
                max_asm_inst_len, last_code_strictly_longest,
                i == last_code_line)
            print(line, file=output_stream)


def _c_array_code_line(offset, code, asm_inst, asm_params, asm_comment,
        max_code_len, max_asm_inst_len, last_code_strictly_longest,
        is_last_code_line):
    """Returns a formatted code line output string."""
    # Code line comments start at a fixed column index calculated based on the
    # longest code line. All the code lines get an extra trailing comma
    # character except for the last one. Note that this means that this extra
    # comma character needs to be taken into consideration when calculating the
    # starting comment column, except when the last code line is strictly
    # longer and any of the other code lines.
    code_string = ", ".join("0x{}".format(x) for x in code.split(" "))
    if not is_last_code_line:
        code_string += ","
    #TODO: Refactor into a printer object that calculates the the comment
    # column only once.
    comment_column_index = 6 * ((max_code_len + 1) // 3) - 2
    if not last_code_strictly_longest:
        comment_column_index += 1
    if asm_params or asm_comment:
        comment = "{:{}} {}{}".format(asm_inst, max_asm_inst_len, asm_params,
            asm_comment)
    else:
        comment = asm_inst
    return "{:{}}  // {} - {}".format(code_string, comment_column_index,
        offset, comment)


if __name__ == "__main__":
    return_code = main()
    if return_code is not None:
        sys.exit(return_code)
