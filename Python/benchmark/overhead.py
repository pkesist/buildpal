import os
import sys
import statistics
import subprocess
import time
from multiprocessing import cpu_count
from collections import defaultdict
from tempfile import mkstemp
from pprint import pprint
import signal

SERVER_PORT = 33441

def print_stats(times):
    pprint(times)
    stats = dict((key, dict(mean=statistics.mean(data), stdev=statistics.pstdev(data))) for key, data in times.items())
    pprint(stats)

def timeit(command, times, ini_file, profile):
    buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    start_time = time.time()
    subprocess.check_call(command, cwd=buildpal_dir)
    times['regular'].append(time.time() - start_time)

    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager',
        '--ui=none', '--ini={}'.format(ini_file),
        '--profile={}'.format(profile)],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    server = subprocess.Popen([sys.executable, '-m', 'buildpal', 'server',
        '--silent', '--port={}'.format(SERVER_PORT)],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    time.sleep(5)
    start_time = time.time()
    subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--no-cp', '--run'] + command + ['--jobs={}'.format(2*cpu_count())], cwd=buildpal_dir)
    times['buildpal'].append(time.time() - start_time)
    os.kill(server.pid, signal.CTRL_BREAK_EVENT)
    os.kill(manager.pid, signal.CTRL_BREAK_EVENT)
    server.wait()
    manager.wait()

    print_stats(times)

ini_handle, ini_file = mkstemp(suffix='.ini')
with os.fdopen(ini_handle, 'wt') as ini:
    ini.write('[local]\n')
    ini.write('node[{}]={}:{}:{}\n'.format(0, 'localhost',
        33441, cpu_count()))

times = defaultdict(list)
repetitions = 1 if len(sys.argv) < 2 else int(sys.argv[1])
for x in range(repetitions):
    timeit([sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc'], times, ini_file, 'local')
