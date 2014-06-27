import pytest
import socket

from buildpal.common.beacon import Beacon

MULTICAST_ADDRESS = '239.192.29.71'
MULTICAST_PORT = 53334

@pytest.fixture(scope='module', params=(
    (4, 31313), (5, 31314), (6, 31315), (7, 31316), (8, 31317), (9, 31318),
    (4, 31313), (5, 31324), (6, 31335), (7, 31346), (8, 31357), (9, 31368),
))
def run_beacon(request):
    beacon = Beacon(request.param[0], request.param[1])
    beacon.start(MULTICAST_ADDRESS, MULTICAST_PORT)
    request.addfinalizer(beacon.stop)
    return request.param[0], request.param[1]

def test_beacon(run_beacon):
    nodes = Beacon.get_nodes_from_multicast(MULTICAST_ADDRESS, MULTICAST_PORT)

    assert len(nodes) == 1
    assert nodes[0]['job_slots'] == run_beacon[0]
    assert nodes[0]['port'] == run_beacon[1]
    assert nodes[0]['hostname'] == socket.getfqdn()
    assert nodes[0]['address'] in (x[4][0] for x in socket.getaddrinfo(family=socket.AF_INET, host='', port=0))


