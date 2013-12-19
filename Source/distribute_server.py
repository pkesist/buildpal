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
        'distribute_manager.py')
    parser.add_argument('--port', dest='port', type=int, default=6064,
        help='TCP port on which server will listen.')
    parser.add_argument('--cpu-hwm', dest='cpu_hwm', type=int, default=None,
        help='CPU high-water mark. In case overall CPU usage exceedes this '
        'number further tasks will be rejected.')
    opts = parser.parse_args()

    if opts.cpu_hwm is not None and (opts.cpu_hwm <= 0 or opts.cpu_hwm > 100):
        raise RuntimeError("CPU high-water mark should be in {1, 2, ..., 100}.")

    if opts.port < 1024 or opts.port > 65535:
        raise RuntimeError("TCP port should be in {1024, 1025, ..., 65535}.")

    compile_worker = CompileWorker('tcp://*:{}'.format(opts.port), opts.cpu_hwm)
    try:
        compile_worker.run()
    except KeyboardInterrupt:
        print("\nShutting down threads...")
        compile_worker.shutdown()
        print("Done.")
        

