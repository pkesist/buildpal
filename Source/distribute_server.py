from multiprocessing.connection import Listener
import subprocess
import types
import marshal
address = ('localhost', 6000)

listener = Listener(address)

while True:
    print("Waiting for client...")
    conn = listener.accept()
    print('connection accepted from', listener.last_accepted)
    try:
        code = conn.recv()
        code = marshal.loads(code)
        function = types.FunctionType(code, globals())
        request = conn.recv()
        conn.send(function(request))
    except:
        print("Failed to execute client task.")
        