import os
import sys
import subprocess
from tempfile import mkstemp
from multiprocessing import cpu_count
import time

from buildpal.common.beacon import get_nodes_from_beacons

nodes = get_nodes_from_beacons()
if not nodes:
    raise Exception("No nodes detected.")

ini_handle, ini_file = mkstemp(suffix='.ini')
with os.fdopen(ini_handle, 'wt') as ini:
    ini.write('[distributed]\n')
    for index, node in enumerate(nodes):
        ini.write('node[{}]={}:{}\n'.format(index, node['address'],
            node['port']))

manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager',
    '--ui=gui', '--ini={}'.format(ini_file)])

buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
start_time = time.time()
subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--run'] + [sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc'] + ['--jobs={}'.format(64)], cwd=buildpal_dir)
times = {}
times['buildpal_compiler_subst'] = time.time() - start_time
print(times)
manager.terminate()
