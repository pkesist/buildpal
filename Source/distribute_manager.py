from multiprocessing.managers import BaseManager

import sys

#hosts = [('localhost', 6060)]
hosts = [('localhost', 6070), ('speedtest', 6070)]
last_host = None

def get_host():
    global hosts
    global last_host
    if last_host is not None:
        last_host = (last_host + 1) % len(hosts)
    else:
        last_host = 0
    return hosts[last_host]
        

class DistributeManager(BaseManager):
    pass

DistributeManager.register('get_host', callable=get_host)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("""\
Usage:
    {} <manager_id> [<passkey>]
""".format(sys.argv[0]))

    id = sys.argv[1]
    print("Spawning a manager with id '{}'".format(id))
    manager = DistributeManager(r"\\.\pipe\{}".format(id), b"")
    server = manager.get_server()
    server.serve_forever()


