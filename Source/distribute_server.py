#! python3.3
from time import sleep

from Common import bind_to_random_port
from Server import CompileWorker
    
from multiprocessing import cpu_count

import argparse
import configparser
import os
import sys
import zmq

default_script = 'distribute_server.ini'

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Command line parameters for '
        'distribute_server')
    parser.add_argument('--port', '-p', metavar="#", dest='port', type=int, default=6064,
        help='TCP port on which server will listen. (default=6064)')
    parser.add_argument('--jobs', '-j', metavar="#", dest='compile_slots', type=int,
        default=cpu_count(), help='Number of jobs, i.e. number of compiler '
        'processes that can run concurrently. (default=number of cores)')
    opts = parser.parse_args()

    if opts.compile_slots is not None and (opts.compile_slots <= 0 or
            opts.compile_slots > 4 * cpu_count()):
        raise RuntimeError("CPU high-water mark should be in "
            "{{1, 2, ..., {}}}.".format(4 * cpu_count()))

    if opts.port < 1024 or opts.port > 65535:
        raise RuntimeError("TCP port should be in {1024, 1025, ..., 65535}.")

    compile_worker = CompileWorker('tcp://*:{}'.format(opts.port), opts.compile_slots)
    try:
        compile_worker.run()
    except KeyboardInterrupt:
        print("\nShutting down threads...")
        compile_worker.shutdown()
        print("Done.")
        

