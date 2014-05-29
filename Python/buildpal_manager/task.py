from .compile_session import SessionResult
from buildpal_common import Timer

from time import time
import logging

class Task(Timer):
    def __init__(self, task_dict):
        super().__init__()
        self.__dict__.update(task_dict)
        self.sessions_running = set()
        self.sessions_finished = set()
        self.completed_by_session = None

    @property
    def compiler_info(self):
        return self.command_processor.compiler_info

    @property
    def compiler(self):
        return self.command_processor.compiler

    @property
    def executable(self):
        return self.command_processor.executable

    def is_completed(self):
        return bool(self.completed_by_session)

    def register_session(self, session):
        session.node.add_tasks_sent()
        self.note_time('assigned to a server session', 'waiting for server')
        self.sessions_running.add(session)

    def register_completion(self, session):
        if self.completed_by_session:
            return False
        self.note_time('completed notification', 'remote completion notification')
        self.completed_by_session = session
        for other_session in (s for s in self.sessions_running if s != session):
            other_session.cancel()
        return True

    def cannot_distribute(self):
        # For some reason or other, this task cannot be distributed.
        # Make the client compile it. After that the processing will
        # continue as if the server node did it.
        self.command_processor.compile_on_client(self)

    def session_completed(self, session, *args):
        assert session.result is not None
        assert session in self.sessions_running
        self.sessions_running.remove(session)
        self.sessions_finished.add(session)
        session.node.process_session_result(session.result)
        # No more sessions.
        if not self.sessions_running and self.completed_by_session:
            self.command_processor.all_sessions_done(self)

        def task_completed():
            node = session.node
            node.timer().add_time("session duration",
                session.time_completed - session.time_started)
            node.add_total_time(
                session.time_completed - session.time_started)
            result = (session.retcode, session.stdout,
                session.stderr)
            self.command_processor.task_completed(self, result)

        def output_file_arrived(future):
            try:
                session.task.output = future.result()
            except Exception:
                # TODO:
                pass
            else:
                task_completed()

        if session.result == SessionResult.success:
            assert session == self.completed_by_session
            self.note_time('session successful', 'waiting for session result')
            if session.retcode == 0:
                session.output_file_future.add_done_callback(
                    output_file_arrived)
            else:
                task_completed()

    def task_completed(self, retcode, stdout, stderr):
        self.command_processor.task_completed(self, (retcode, stdout, stderr))

    def get_info(self):
        assert not self.sessions_running
        return {
            'source' : self.source,
            'pch_file' : self.pch_file[0] if self.pch_file else None,
            'sessions' : list(session.get_info() for session in
                self.sessions_finished),
            'times' : list(dict(time_point_name=a, time_point=b) for a, b in self.times.items())
        }
