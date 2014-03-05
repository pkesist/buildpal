from .compile_session import SessionResult

from time import time

class Task:
    def __init__(self, task_dict):
        self.__dict__.update(task_dict)
        self.sessions_running = set()
        self.sessions_finished = set()
        self.first_session = None
        self.completed_by_session = None
        self.last_time = time()
        self.times = {}
        self.task_result = None

    def note_time(self, name):
        curr_time = time()
        self.times[name], self.last_time = curr_time - self.last_time, curr_time

    def compiler_info(self):
        return self.command_processor.compiler_info

    def compiler(self):
        return self.command_processor.compiler()

    def executable(self):
        return self.command_processor.executable()

    def is_completed(self):
        return bool(self.completed_by_session)

    def register_session(self, session):
        if not self.sessions_running:
            self.first_session = session
            session.node.add_tasks_sent()
            self.note_time('assigned to a server session')
        else:
            session.node.add_tasks_stolen()
        self.sessions_running.add(session)

    def register_completion(self, session):
        if self.completed_by_session:
            return False
        self.note_time('task completed notification received')
        self.completed_by_session = session
        if session != self.first_session:
            session.node.add_tasks_successfully_stolen()
        for other_session in (s for s in self.sessions_running if s != session):
            other_session.cancel()
        return True

    def session_completed(self, session, *args):
        assert session.result is not None
        assert session in self.sessions_running
        self.sessions_running.remove(session)
        self.sessions_finished.add(session)
        session_succeeded = False
        if session.result == SessionResult.success:
            assert session == self.completed_by_session
            self.note_time('task result received')
            session.node.add_tasks_completed()
            session.node.timer().add_time("session duration",
                session.time_completed - session.time_started)
            session.node.add_total_time(
                session.time_completed - session.time_started)
            self.task_result = (session.retcode, session.stdout,
                session.stderr)
            if session.retcode == 0:
                self.disk_future = session.write_to_disk_future
        elif session.result == SessionResult.failure:
            session.node.add_tasks_failed()
        elif session.result == SessionResult.cancelled:
            session.node.add_tasks_cancelled()
        elif session.result == SessionResult.timed_out:
            session.node.add_tasks_timed_out()
        elif session.result == SessionResult.too_late:
            session.node.add_tasks_too_late()
        if not self.sessions_running and self.task_result is not None:
            self.command_processor.task_completed(self)

    def get_info(self):
        assert not self.sessions_running
        assert self.completed_by_session is not None
        return {
            'source' : self.source,
            'pch_file' : self.pch_file[0] if self.pch_file else None,
            'sessions' : list(session.get_info() for session in
                self.sessions_finished)
        }
