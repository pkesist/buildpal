#! python3.3
import os
import subprocess
import sys
import zmq

def execute(compiler, manager_port, command):
    zmq_ctx = zmq.Context()
    conn = zmq_ctx.socket(zmq.DEALER)
    conn.connect("tcp://localhost:{}".format(manager_port))
    task = [compiler.encode(), os.getcwd().encode()]
    task.extend(x.encode() for x in command)
    conn.send_multipart(task)
    response = conn.recv()
    assert response == b"TASK_RECEIVED"
    while True:
        request = conn.recv_multipart()
        if request[0] == b'EXECUTE_AND_EXIT':
            cmd = [x.decode() for x in request[1:]]
            return subprocess.call(cmd)
        elif request[0] == b'EXECUTE_GET_OUTPUT':
            cmd = [x.decode() for x in request[1:]]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                stdout, stderr = proc.communicate()
            conn.send_multipart([str(proc.returncode).encode(), stdout, stderr])
        elif request[0] == b'EXIT':
            return int(request[1])
        elif request[0] == b'COMPLETED':
            retcode = int(request[1])
            stdout = request[2].decode()
            stderr = request[3].decode()
            sys.stdout.write(stdout)
            if stderr:
                sys.stderr.write("---------------------------- STDERR ----------------------------\n")
                sys.stderr.write(stderr)
                sys.stderr.write("----------------------------------------------------------------\n")
            return retcode
        elif request[0] == b'GETENV':
            conn.send_multipart([os.environ.get(request[1].decode(), '').encode()])
        else:
            print("ERROR: GOT {}".format(request[0]))
            return -1

if __name__ == '__main__':
    sys.exit(execute(sys.argv[1], sys.argv[2], sys.argv[3:]))