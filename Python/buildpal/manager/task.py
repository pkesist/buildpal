from .compile_session import SessionResult
from buildpal.common import Timer

from time import time
import logging

class PreprocessTask:
    def __init__(self, source, macros, includes, sysincludes, forced_includes,
            pch_header):
        self.source = source
        self.macros = macros
        self.includes = includes
        self.sysincludes = sysincludes
        self.forced_includes = forced_includes
        self.pch_header = pch_header

class Task(Timer):
    def __init__(self, server_task, preprocess_task, command_processor, output,
            result_files, pch_file, source):
        super().__init__()
        self.server_task = server_task
        self.preprocess_task = preprocess_task
        self.command_processor = command_processor
        self.output = output
        self.result_files = result_files
        self.pch_file = pch_file
        self.source = source

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
        return self.completed_by_session is not None

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
        """
        Notifies the task that a session is completed.

        Returns False if the task is to be rescheduled.
        """
        assert session.result is not None
        assert session in self.sessions_running
        self.sessions_running.remove(session)
        self.sessions_finished.add(session)
        session.node.process_session_result(session.result)

        # In case we got a server failure, reschedule the task.
        if session.result in (SessionResult.failure,
                              SessionResult.timed_out,
                              SessionResult.terminated):
            # We owe the result, but we failed.
            if self.completed_by_session == session:
                self.completed_by_session = None

            return self.is_completed() or self.sessions_running

        # No more sessions.
        if not self.sessions_running and self.is_completed():
            self.command_processor.all_sessions_done(self)

        if session.result == SessionResult.success:
            assert session == self.completed_by_session
            self.note_time('session successful', 'waiting for session result')
            node = session.node
            node.timer().add_time("session duration",
                session.time_completed - session.time_started)
            node.add_total_time(
                session.time_completed - session.time_started)
            result = (session.retcode, session.stdout,
                session.stderr)
            self.command_processor.task_completed(self, result)
        return True

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
