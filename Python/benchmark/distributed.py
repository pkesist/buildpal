from collections import defaultdict
import os
import sys
import subprocess
from tempfile import mkstemp
import signal
import socket
import time
import statistics
from pprint import pprint

from buildpal.common.beacon import get_nodes_from_beacons
from buildpal.common import msg_to_bytes


repetitions = 1 if len(sys.argv) < 2 else int(sys.argv[1])

nodes = get_nodes_from_beacons()
if not nodes:
    raise Exception("No nodes detected.")

ini_handle, ini_file = mkstemp(suffix='.ini')
with os.fdopen(ini_handle, 'wt') as ini:
    ini.write('[distributed]\n')
    for index, node in enumerate(nodes):
        ini.write('node[{}]={}:{}:{}\n'.format(index, node['address'],
            node['port'], node['job_slots']))

def reset_nodes():
    for node in nodes:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((node['address'], node['port']))
            for buffer in msg_to_bytes([b'RESET']):
                sock.send(buffer)

def print_stats(times, nodes):
    print("Nodes:")
    for node in nodes:
        print("    {}:{}:{}".format(node['address'], node['port'], node['job_slots']))
    pprint(times)
    stats = dict((key, dict(mean=statistics.mean(data), stdev=statistics.pstdev(data))) for key, data in times.items())
    pprint(stats)

command = [sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc']

times = defaultdict(list)
buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

for x in range(repetitions):
    reset_nodes()
    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager',
        '--ui=gui', '--ini={}'.format(ini_file), '--profile=distributed'],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    start_time = time.time()
    result = subprocess.call([sys.executable, '-m', 'buildpal', 'client', '--no-cp', '--run'] + command + ['--jobs={}'.format(64)], cwd=buildpal_dir)
    times['buildpal'].append(time.time() - start_time)
    os.kill(manager.pid, signal.CTRL_BREAK_EVENT)
    manager.wait()

    print_stats(times, nodes)