from multiprocessing.connection import Listener
from multiprocessing import Pool, Process
from multiprocessing.reduction import reduce_connection
import subprocess
import traceback
import types
import marshal
import sys

address = ('', 6060)

listener = Listener(address, 'AF_INET')

def work(conn):
    try:
        conn = conn[0](*conn[1])
        task = conn.recv()
        task.process(conn)
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
        tasks = list(filter(lambda task : not task.ready(), tasks))
        print_tasks()
        conn = listener.accept()
        tasks.append(pool.apply_async(func=work, args=(reduce_connection(conn),)))

        