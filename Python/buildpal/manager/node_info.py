from .timer import Timer
from .compile_session import SessionResult

from time import time

class NodeInfo:
    def __init__(self, node_dict):
        self._node_dict = node_dict
        self._tasks_completed  = 0
        self._tasks_failed     = 0
        self._tasks_sent       = 0
        self._tasks_cancelled  = 0
        self._tasks_too_late   = 0
        self._tasks_timed_out  = 0
        self._total_time       = 0
        self._tasks_terminated = 0
        self._tasks_change     = None
        self._avg_tasks = {}
        self._timer = Timer()

    def node_id(self):
        return "{}:{}".format(self._node_dict['hostname'],
            self._node_dict['port'])

    def average_task_time(self):
        tasks_completed = self.tasks_completed()
        return self.total_time() / tasks_completed if tasks_completed else 0

    def tasks_terminated(self): return self._tasks_terminated

    def tasks_sent(self): return self._tasks_sent

    def tasks_cancelled(self): return self._tasks_cancelled

    def tasks_completed(self): return self._tasks_completed

    def tasks_failed(self): return self._tasks_failed

    def tasks_too_late(self): return self._tasks_too_late

    def tasks_timed_out(self): return self._tasks_timed_out

    def tasks_pending(self): return (self.tasks_sent() -
        self.tasks_completed() - self.tasks_failed() - self.tasks_too_late() -
        self.tasks_cancelled() - self.tasks_timed_out() -
        self.tasks_terminated())

    def total_time(self): return self._total_time

    def average_tasks(self):
        avg_tasks = self._avg_tasks
        regular_duration = sum((duration for duration in avg_tasks.values()))
        weighted_duration = sum((duration * tasks for tasks, duration in avg_tasks.items()))
        return (weighted_duration / regular_duration) if regular_duration else 0

    def __tasks_pending_about_to_change(self):
        tasks_pending = self.tasks_pending()
        if tasks_pending > 0:
            current_time = time()
            duration = current_time - self._tasks_change
            self._tasks_change = current_time
            self._avg_tasks.setdefault(tasks_pending, 0)
            self._avg_tasks[tasks_pending] += duration
        else:
            self._tasks_change = time()

    def process_session_result(self, result):
        self.__tasks_pending_about_to_change()
        if result == SessionResult.success:
            self._tasks_completed += 1
        elif result == SessionResult.failure:
            self._tasks_failed += 1
        elif result == SessionResult.cancelled:
            self._tasks_cancelled += 1
        elif result == SessionResult.timed_out:
            self._tasks_timed_out += 1
        elif result == SessionResult.too_late:
            self._tasks_too_late += 1
        elif result == SessionResult.terminated:
            self._tasks_terminated += 1

    def add_tasks_sent(self):
        self.__tasks_pending_about_to_change()
        self._tasks_sent += 1

    def add_total_time(self, value): self._total_time += value

    def timer(self):
        return self._timer

    def node_dict(self):
        return self._node_dict
