# Uses gawk extensions:
#  - multidimensional arrays
#  - gensub() function

function fail(message) {
    print "ERROR:", message
    exit_code = -2
    exit exit_code
}

function repeated(count, char,     buffer) {
    if (count) {
        buffer = sprintf("%0*d", count, 0)
        gsub(/0/, char, buffer)
        return buffer
    }
}

function strtohex(string) {
    return strtonum(sprintf("0x%s", string))
}

function parse_code_line(line, parsed,     parts) {
    split("", parsed)  # clear the `parsed` array
    if (current_code_line_index) {
        # Line continuation.
        if (match(line, /^\t([0-9a-fA-f]{2}( [0-9a-fA-f]{2})*)(\t+(.*))?$/,
            parts)) {
            parsed[2] = parts[1]  # continued binary code
            if (parts[4])
                parsed[3] = parts[4]  # assembler code + comments
            return 1
        }
    } else {
        # New code line.
        if (match(line,
            /^  ([0-9a-fA-F]+)\t([0-9a-fA-f]{2}( [0-9a-fA-f]{2})*)(\t+(.*))?$/,
            parts)) {
            parsed[1] = parts[1]  # offset
            parsed[2] = parts[2]  # binary code
            if (parts[5])
                parsed[3] = parts[5]  # assembler code + comments
            return 1
        }
    }
}

function collect_output_line(line,     parsed_code, x, last_offset, last_instruction_count, offset, code_length) {
    output[NR] = line
    if (parse_code_line(line, parsed_code)) {
        if (current_code_line_index) {
            # Continuing a previous code line.
            partial_code_lines[NR] = ""
            code_lines[current_code_line_index][2] = sprintf("%s %s",
                code_lines[current_code_line_index][2], parsed_code[2])
            if (3 in parsed_code)
                code_lines[current_code_line_index][3] = parsed_code[3]
        } else {
            # Starting a new code line.
            current_code_line_index = NR
            if (length(code_lines)) {
                last_offset = strtohex(code_lines[prev_code_line_index][1])
                last_instruction_count = instruction_count(length(code_lines[prev_code_line_index][2]))
                offset = strtohex(parsed_code[1])
                if (offset != last_offset + last_instruction_count) {
                    fail(sprintf("bad offset at code line %d", NR))
                }
            }
            for (x in parsed_code)
                code_lines[current_code_line_index][x] = parsed_code[x]
        }
        if (3 in code_lines[current_code_line_index]) {
            # Code line completed.
            code_length = length(code_lines[current_code_line_index][2])
            if (code_length > max_code_length)
                max_code_length = code_length
            prev_code_line_index = current_code_line_index
            current_code_line_index = ""
        }
    } else if (current_code_line_index)
        # No need to check for this at end of file because if we do not get
        # another output line when a code line continuation is expected, an
        # 'incomplete procedure' error will get reported anyway.
        fail(sprintf("missing code line continuation at line %d", NR))
}

function instruction_count(raw_instruction_code_length) {
    # each instruction has two bytes + space except after the last
    return (raw_instruction_code_length + 1) / 3
}

function output_code_line(indent, line_index,     code_output_width, formatted_code) {
    code_output_width = 6 * instruction_count(max_code_length) - 1
    formatted_code = tolower(code_lines[line_index][2])
    formatted_code = gensub(/([0-9a-f]{2})/, "0x\\0,", "g", formatted_code)
    if (line_index == prev_code_line_index)
        formatted_code = substr(formatted_code, 1, length(formatted_code) - 1)
    printf "%s%-*s  // %s - %s\n", indent, code_output_width, formatted_code,
        code_lines[line_index][1], code_lines[line_index][3]
}

function output_comment_line(indent, line_index) {
    printf indent
    print "//", output[line_index]
}

function output_line(indent, line_index) {
    if (line_index in code_lines)
        output_code_line(indent, line_index)
    else if (!(line_index in partial_code_lines))
        output_comment_line(indent, line_index)
}

function output_lines(output,     indent, i) {
    PROCINFO["sorted_in"] = "@ind_num_asc"
    for (i in output)
        output_line(INDENT, i)
}

BEGIN {
    if (!func_name)
        fail("function name not specified (use '-v func_name=...' to specify)")

    # Constants.
    STATE_NOT_COLLECTING = 0
    STATE_COLLECTING = 1
    STATE_COLLECTED = 2
    DECORATED_FUNC_NAME = sprintf("[^[:space:]]*%s[^[:space:]]*", func_name)
    PROC_START = sprintf("^%s PROC\t+; %s$", DECORATED_FUNC_NAME, func_name)
    PROC_END = sprintf("^%s ENDP\t+; %s$", DECORATED_FUNC_NAME, func_name)
    INDENT = repeated(indent, " ")

    # Global data.
    exit_code = 0
    state = STATE_NOT_COLLECTING
    max_code_length = 0
    current_code_line_index = 0
    split("", code_lines)  # declare `code_lines` as array
    split("", partial_code_lines)  # declare `partial_code_lines` as array
}

END {
    if (!exit_code)
    {
        if (state == STATE_NOT_COLLECTING)
            fail("missing procedure")
        if (state != STATE_COLLECTED)
            fail("procedure incomplete")
        if (max_code_length == 0)
            fail("missing procedure code")
        output_lines(output)
    }
}

$0 ~ PROC_START {
    if (state != STATE_NOT_COLLECTING)
        fail("multiple procedure start")
    state = STATE_COLLECTING
    print "////////////////////////////////////////////////////////////////////////////////"
    print "//"
    print "// Automatically generated - do not edit"
    print "//"
    print "////////////////////////////////////////////////////////////////////////////////"
}

state == STATE_COLLECTING {collect_output_line($0)}

$0 ~ PROC_END {
    if (state != STATE_COLLECTING)
        fail("unexpected ENDP")
    state = STATE_COLLECTED
}
