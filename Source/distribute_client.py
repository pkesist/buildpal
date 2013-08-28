#! python3.3
import os
import subprocess
import sys
import zmq

from utils import send_compressed_file

def execute(compiler, manager_port, command):
    zmq_ctx = zmq.Context()
    conn = zmq_ctx.socket(zmq.DEALER)
    conn.connect("tcp://localhost:{}".format(manager_port))
    conn.send_pyobj((compiler, os.getcwd(), command))
    response = conn.recv_pyobj()
    assert response == "TASK_RECEIVED"
    while True:
        request = conn.recv_pyobj()
        if request == 'PREPROCESS':
            preprocess_call = conn.recv_pyobj()
            p = subprocess.Popen(preprocess_call, stdout=subprocess.PIPE)
            send_compressed_file(conn.send_pyobj, p.stdout)
        elif request == 'EXECUTE_AND_EXIT':
            command = conn.recv_pyobj()
            return subprocess.call(command)
        elif request == "EXECUTE_GET_OUTPUT":
            command = conn.recv_pyobj()
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                stdout, stderr = proc.communicate()
                retcode = proc.returncode
            conn.send_pyobj((retcode, stdout, stderr))
        elif request == 'EXIT':
            retcode = conn.recv_pyobj()
            return retcode
        elif request == 'COMPLETED':
            retcode, stdout, stderr = conn.recv_pyobj()
            sys.stdout.write(stdout.decode())
            if stderr:
                sys.stderr.write("---------------------------- STDERR ----------------------------\n")
                sys.stderr.write(stderr.decode())
                sys.stderr.write("----------------------------------------------------------------\n")
            return retcode
        elif request == "GETENV":
            envvar = conn.recv_pyobj()
            conn.send_pyobj(os.environ.get(envvar, ''))
        else:
            print("GOT {}".format(request))
            return -1

if __name__ == '__main__':
    sys.exit(execute(sys.argv[1], sys.argv[2], sys.argv[3:]))