from .timer import Timer

from time import time

class NodeInfo:
    def __init__(self, node_dict, index):
        self._node_dict = node_dict
        self._index = index
        self._tasks_completed  = 0
        self._tasks_failed     = 0
        self._tasks_sent       = 0
        self._total_time       = 0
        self._open_connections = 0
        self._tasks_change     = None
        self._avg_tasks = {}
        self._timer = Timer()

    def index(self):
        return self._index

    def average_task_time(self):
        tasks_completed = self.tasks_completed()
        return self.total_time() / tasks_completed if tasks_completed else 0

    def connection_open(self): self._open_connections += 1

    def connection_closed(self): self._open_connections -= 1

    def connections(self): return self._open_connections

    def tasks_sent(self): return self._tasks_sent

    def tasks_completed(self): return self._tasks_completed

    def tasks_failed(self): return self._tasks_failed

    def tasks_processing(self): return self.tasks_sent() - self.tasks_completed() - self.tasks_failed()

    def total_time(self): return self._total_time

    def average_tasks(self):
        avg_tasks = self._avg_tasks
        regular_duration = sum((duration for duration in avg_tasks.values()))
        weighted_duration = sum((duration * tasks for tasks, duration in avg_tasks.items()))
        return (weighted_duration / regular_duration) if regular_duration else 0

    def __tasks_processing_about_to_change(self):
        tasks_processing = self.tasks_processing()
        if tasks_processing > 0:
            current_time = time()
            duration = current_time - self._tasks_change
            self._tasks_change = current_time
            self._avg_tasks.setdefault(tasks_processing, 0)
            self._avg_tasks[tasks_processing] += duration
        else:
            self._tasks_change = time()

    def add_tasks_sent(self):
        self.__tasks_processing_about_to_change()
        self._tasks_sent += 1

    def add_tasks_completed(self):
        self.__tasks_processing_about_to_change()
        self._tasks_completed += 1

    def add_tasks_failed(self): self._tasks_failed += 1

    def add_total_time(self, value): self._total_time += value

    def timer(self):
        return self._timer

    def node_dict(self):
        return self._node_dict
