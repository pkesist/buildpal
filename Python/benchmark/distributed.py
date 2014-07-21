from collections import defaultdict
import os
import sys
import subprocess
from tempfile import mkstemp
from multiprocessing import cpu_count
import socket
import time

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

command = [sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc']

times = defaultdict(list)
buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

for x in range(repetitions):
    reset_nodes()
    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager',
        '--ui=none', '--ini={}'.format(ini_file), '--profile=distributed'])
    start_time = time.time()
    result = subprocess.call([sys.executable, '-m', 'buildpal', 'client', '--run'] + command + ['--jobs={}'.format(64)], cwd=buildpal_dir)
    if result != 0:
        import pdb; pdb.set_trace()
    times['buildpal_compiler_subst'].append(time.time() - start_time)
    manager.terminate()

    reset_nodes()
    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager',
        '--ui=none', '--ini={}'.format(ini_file), '--profile=distributed'])
    start_time = time.time()
    result = subprocess.call([sys.executable, '-m', 'buildpal', 'client', '--no-cp', '--run'] + command + ['--jobs={}'.format(64)], cwd=buildpal_dir)
    if result != 0:
        import pdb; pdb.set_trace()
    times['buildpal_no_cp'].append(time.time() - start_time)
    manager.terminate()

import statistics
from pprint import pprint
print("Nodes:")
for node in nodes:
    print("    {}:{}:{}".format(node['address'], node['port'], node['job_slots']))
stats = dict((key, dict(mean=statistics.mean(data), stdev=statistics.pstdev(data))) for key, data in times.items())
pprint(stats)
