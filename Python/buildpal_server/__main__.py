from .server_runner import ServerRunner

from time import sleep
from multiprocessing import cpu_count

import argparse
import configparser
import os
import sys

def main(args, terminator=None):
    parser = argparse.ArgumentParser(description='Command line parameters for '
        'buildpal_server')
    parser.add_argument('--port', '-p', metavar="#", dest='port', type=int, default=0,
        help='TCP port on which server will listen. (default=ephemeral)')
    parser.add_argument('--max-jobs', '-j', metavar="#", dest='compile_slots', type=int,
        default=cpu_count(), help='Number of jobs, i.e. number of compiler '
        'processes that can run concurrently. (default=number of cores)')
    parser.add_argument('--silent', '-s', action='store_true', dest='silent',
        default=False, help='Do not print any output.')
    parser.add_argument('--debug', '-d', action='store_true', dest='debug',
        default=False, help='Enable debug logging.')
    opts = parser.parse_args(args)

    if opts.debug:
        import logging
        logging.basicConfig(fileName='server_debug.log', level=logging.DEBUG)

    if opts.compile_slots is not None and (opts.compile_slots <= 0 or
            opts.compile_slots > 4 * cpu_count()):
        raise RuntimeError("Max jobs  mark should be in "
            "{{1, 2, ..., {}}}.".format(4 * cpu_count()))

    server_runner = ServerRunner(opts.port, opts.compile_slots)
    try:
        server_runner.run(terminator, opts.silent)
    except KeyboardInterrupt:
        if not opts.silent:
            print("\nShutting down...")
        server_runner.shutdown()
        if not opts.silent:
            print("Done.")
        

if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
    main(sys.argv[1:])
