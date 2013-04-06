from multiprocessing.connection import Listener
from multiprocessing import Pool, Process
from multiprocessing.reduction import reduce_connection
import subprocess
import traceback
import types
import marshal
import sys

try:
    import psutil
    psutil_available = True
except:
    psutil_available = False
    

address = ('localhost', 6000)

listener = Listener(address)

def work(conn):
    try:
        conn = conn[0](*conn[1])
        code, param = conn.recv()
        function = types.FunctionType(marshal.loads(code), globals())
        cpu_usage = psutil.cpu_percent(percpu=True) if psutil_available else None
        freemem = psutil.virtual_memory().available if psutil_available else None
        function(param, conn, cpu_usage, freemem)
    except:
        print("Failed to execute client task.")
        traceback.print_exc()


def print_tasks():
    global tasks
    sys.stdout.write("Running {} tasks.{}".format(len(tasks), '\r'))

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            processes = int(sys.argv[1])
    except:
        processes = 8
    print("Spawning {} worker processes.".format(processes))
    pool = Pool(processes=processes)
    print("Starting server.")
    global tasks
    tasks = []
    while True:
        print_tasks()
        to_remove = []
        for i in range(len(tasks)):
            task = tasks[i]
            if task.ready():
                to_remove.append(i)
        to_remove.reverse()
        for a in to_remove:
            del tasks[a]
        conn = listener.accept()
        tasks.append(pool.apply_async(func=work, args=(reduce_connection(conn),)))

        