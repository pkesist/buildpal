from multiprocessing.connection import Listener
from multiprocessing import Pool, Process
from multiprocessing.reduction import reduce_connection
import subprocess
import traceback
import types
import marshal
address = ('localhost', 6000)

listener = Listener(address)

def work(conn):
    try:
        conn = conn[0](*conn[1])
        code, param = conn.recv()
        function = types.FunctionType(marshal.loads(code), globals())
        function(param, conn)
    except:
        print("Failed to execute client task.")
        traceback.print_exc()


if __name__ == "__main__":
    pool = Pool(processes=6)
    while True:
        print("Waiting for client...")
        conn = listener.accept()
        print('connection accepted from', listener.last_accepted)
        try:
            pool.apply_async(func=work, args=(reduce_connection(conn),))
        except:
            print("Failed to execute client task.")
            traceback.print_exc()
        