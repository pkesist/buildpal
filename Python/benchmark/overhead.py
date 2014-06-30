import os
import sys
import subprocess
import time
from multiprocessing import cpu_count

def timeit(command):
    times = {}

    buildpal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    start_time = time.time()
    subprocess.check_call(command, cwd=buildpal_dir)
    times['regular'] = time.time() - start_time

    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager', '--ui=none'])
    server = subprocess.Popen([sys.executable, '-m', 'buildpal', 'server', '--silent'])
    time.sleep(5)
    start_time = time.time()
    subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--run'] + command + ['--jobs={}'.format(2*cpu_count())], cwd=buildpal_dir)
    times['buildpal_compiler_subst'] = time.time() - start_time
    server.terminate()
    manager.terminate()

    manager = subprocess.Popen([sys.executable, '-m', 'buildpal', 'manager', '--ui=none'])
    server = subprocess.Popen([sys.executable, '-m', 'buildpal', 'server', '--silent'])
    time.sleep(5)
    start_time = time.time()
    subprocess.check_call([sys.executable, '-m', 'buildpal', 'client', '--no-cp', '--run'] + command + ['--jobs={}'.format(2*cpu_count())], cwd=buildpal_dir)
    times['buildpal_no_createproc'] = time.time() - start_time 
    server.terminate()
    manager.terminate()
    return times


all_times = {}
boost_times = all_times.setdefault('Boost', [])
for x in range(5):
    boost_times.append(timeit([sys.executable, 'setup.py', 'build_boost', '--complete-build', '--force', '--compiler=msvc']))

with open('boost_times.dat', 'w') as file:
    from pprint import pprint
    pprint(boost_times, stream=file)




