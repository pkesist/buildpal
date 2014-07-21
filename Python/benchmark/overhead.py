import os
import sys
import subprocess
import time
from multiprocessing import cpu_count
from collections import defaultdict

def timeit(command, times):
    buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    start_time = time.time()
    subprocess.check_call(command, cwd=buildpal_dir)
    times['regular'].append(time.time() - start_time)

    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager', '--ui=none'])
    server = subprocess.Popen([sys.executable, '-m', 'buildpal', 'server', '--silent'])
    time.sleep(5)
    start_time = time.time()
    subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--run'] + command + ['--jobs={}'.format(2*cpu_count())], cwd=buildpal_dir)
    times['buildpal_compiler_subst'].append(time.time() - start_time)
    server.terminate()
    manager.terminate()

    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager', '--ui=none'])
    server = subprocess.Popen([sys.executable, '-m', 'buildpal', 'server', '--silent'])
    time.sleep(5)
    start_time = time.time()
    subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--no-cp', '--run'] + command + ['--jobs={}'.format(2*cpu_count())], cwd=buildpal_dir)
    times['buildpal_no_createproc'].append(time.time() - start_time)
    server.terminate()
    manager.terminate()
    return times


repetitions = 1 if len(sys.argv) < 2 else int(sys.argv[1])
times = defaultdict(list)
for x in range(repetitions):
    timeit([sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc'], times)

import statistics
from pprint import pprint
stats = dict((key, dict(mean=statistics.mean(data), stdev=statistics.pstdev(data))) for key, data in times.items())
pprint(stats)
