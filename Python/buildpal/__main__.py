import argparse
from multiprocessing import cpu_count

def main(argv, terminator=None):
    parser = argparse.ArgumentParser(argv[0])
    subparsers = parser.add_subparsers(dest='which')

    client_parser = subparsers.add_parser('client', aliases=['cli', 'c'])
    client_parser.add_argument('--ui', choices=['gui', 'console', 'none'],
        default='gui', help='Select user interface')
    client_parser.add_argument('--port', dest='port', type=str, default=None,
        help='Port on which manager should run.')
    client_parser.add_argument('--ini', dest='ini_file', type=str, default=None,
        help='Specify .ini file.')
    client_parser.add_argument('--debug', '-d', action='store_true', dest='debug',
        default=False, help='Enable debug logging.')
    client_parser.add_argument('--profile', type=str, default=None,
        help='Profile to use. Must be present in the .ini file.')
    client_parser.add_argument('--connect', dest='connect', type=str, default=None,
        help='Manager port to connect to.')
    client_parser.add_argument('--run', nargs=argparse.REMAINDER,
        help='Trailing arguments specify command to run.')

    server_parser = subparsers.add_parser('server', aliases=['srv', 's'])
    server_parser.add_argument('--port', '-p', metavar="#", type=int, default=0,
        help='TCP port on which server will listen. (default=ephemeral)')
    server_parser.add_argument('--max-jobs', '-j', metavar="#",
        dest='compile_slots', type=int, default=cpu_count(),
        help='Number of jobs, i.e. number of compiler '
        'processes that can run concurrently. (default=number of cores)')
    server_parser.add_argument('--silent', '-s', action='store_true',
        dest='silent', default=False, help='Do not print any output.')
    server_parser.add_argument('--debug', '-d', action='store_true',
        dest='debug', default=False, help='Enable debug logging.')

    opts = parser.parse_args(argv[1:])
    if opts.which and opts.which[0] == 's':
        from buildpal.server.__main__ import main as server_main
        return server_main(opts, terminator)
    elif opts.which and opts.which[0] == 'c':
        from buildpal.manager.__main__ import main as client_main
        return client_main(opts, terminator)
    else:
        parser.print_help()

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv) or 0)

