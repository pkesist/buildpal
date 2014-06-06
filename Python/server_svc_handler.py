import threading
from multiprocessing import cpu_count

class Terminator:
    def __init__(self):
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def should_stop(self):
        return self._should_stop

class Handler(object):

    # no parameters are permitted; all configuration should be placed in the
    # configuration file and handled in the Initialize() method
    def __init__(self):
        pass

    # called when the service is starting
    def Initialize(self, configFileName):
        self.terminator = Terminator()

    # called when the service is starting immediately after Initialize()
    # use this to perform the work of the service; don't forget to set or check
    # for the stop event or the service GUI will not respond to requests to
    # stop the service
    def Run(self):
        from buildpal.server.runner import ServerRunner
        ServerRunner(0, cpu_count()).run(self.terminator)

    # called when the service is being stopped by the service manager GUI
    def Stop(self):
        self.terminator.stop()

