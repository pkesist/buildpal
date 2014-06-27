from .runner import ServerRunner

from time import sleep
from multiprocessing import cpu_count

import os
import sys

def main(opts, terminator=None):
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
        pass