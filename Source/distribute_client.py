#! python3.3
import os
import subprocess
import sys
import zmq

compiler = b'msvc'
compiler_executable = 'cl.exe'

def find_exe_on_path():
    path = os.environ['PATH']
    for p in path.split(';'):
        name = os.path.join(p, compiler_executable)
        if os.path.exists(name):
            return name

def execute(command):
    zmq_ctx = zmq.Context()
    conn = zmq_ctx.socket(zmq.DEALER)
    manager_port = os.environ.get('DB_MGR_PORT')
    if manager_port is None:
        sys.stderr.write("Set DB_MGR_PORT environment variable.\n")
        return -1
    conn.connect("tcp://localhost:{}".format(manager_port))
    exe = find_exe_on_path()
    if not exe:
        sys.stderr.write('Failed to find compiler executable on PATH.\n')
        return -1
    task = [compiler, exe, os.getcwd().encode()]
    task.extend(x.encode() for x in command)
    conn.send_multipart(task)
    response = conn.recv()
    assert response == b"TASK_RECEIVED"
    while True:
        request = conn.recv_multipart()
        if request[0] == b'EXECUTE_AND_EXIT':
            cmd = request[1].decode()
            return subprocess.call(cmd)
        elif request[0] == b'EXECUTE_GET_OUTPUT':
            cmd = request[1].decode()
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
    sys.exit(execute(sys.argv[1:]))