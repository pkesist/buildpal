from .compile_worker import CompileWorker

from .Messaging import Broker

from multiprocessing import Process

from Common import bind_to_random_port

import zmq

class ServerRunner(Process):
    def __init__(self, port, control_port, processes, run_compiler_sem,
                 file_repository, header_repository, cpu_usage_hwm,
                 task_counter):
        super(ServerRunner, self).__init__()
        print("Starting server on port {} with {} worker processes.".format(
            port, processes))
        if cpu_usage_hwm:
            print("CPU usage hwm is {}%.".format(cpu_usage_hwm))
        self.__port = port
        self.__processes = processes
        self.__run_compiler_sem = run_compiler_sem
        self.__control_address = 'tcp://localhost:{}'.format(control_port)
        self.__file_repository = file_repository
        self.__header_repository = header_repository
        self.__cpu_usage_hwm = cpu_usage_hwm
        self.__task_counter = task_counter

    def run(self):
        broker = Broker(zmq.Context())
        broker.bind_clients('tcp://*:{}'.format(self.__port))
        broker.connect_control(self.__control_address)
        worker_address = 'tcp://localhost:{}'.format(
            bind_to_random_port(broker.servers))
        workers = list((CompileWorker(worker_address, self.__control_address,
            self.__file_repository, self.__header_repository,
            self.__run_compiler_sem, self.__cpu_usage_hwm,
            self.__task_counter)
            for proc in range(self.__processes)))
        for worker in workers:
            worker.start()
        broker.run()
        for worker in workers:
            worker.join()
