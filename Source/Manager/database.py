import os
import sqlite3

from .compile_session import SessionResult

from queue import Queue, Empty
from threading import Thread

class Database:
    tables = ['command', 'task', 'session']

    command_table = [
        {'col_name': 'command', 'col_type': 'TEXT', 'null': False}
    ]

    task_table = [
        {'col_name': 'command_id', 'col_type': 'INTEGER', 'null': False,
            'ref': ('command', 'rowid')},
        {'col_name': 'source'    , 'col_type': 'TEXT'   , 'null': False},
        {'col_name': 'pch_file'  , 'col_type': 'TEXT'   , 'null': True },]

    def convert_enum(type):
        class ConvertEnum:
            @classmethod
            def to_db(cls, data):
                return data.value

            @classmethod
            def from_db(cls, data):
                return type(data)

            @classmethod
            def db_type(cls):
                return 'INTEGER'

        return ConvertEnum

    session_table = [
        {'col_name': 'task_id'  , 'col_type': 'INTEGER', 'null': False,
            'ref': ('task', 'rowid')},
        {'col_name': 'hostname' , 'col_type': 'TEXT'   , 'null': False},
        {'col_name': 'port'     , 'col_type': 'TEXT'   , 'null': False},
        {'col_name': 'started'  , 'col_type': 'REAL'   , 'null': False},
        {'col_name': 'completed', 'col_type': 'REAL'   , 'null': False},
        {'col_name': 'result'   , 'converter': convert_enum(SessionResult),
            'null': False}]

    @classmethod
    def desc_for_table(cls, table_name):
        return cls.__dict__[table_name + '_table']

    def __init__(self, db_file=None):
        self.cleanup = True
        if db_file is None:
            self.db_file = ':memory:'
            self.cleanup = False
        else:
            self.db_file = db_file
            try:
                os.remove(self.db_file)
            except FileNotFoundError:
                pass
        sqlite3.enable_shared_cache(True)

    def close(self):
        if self.cleanup:
            try:
                os.remove(self.db_file)
            except FileNotFoundError:
                pass

    def get_connection(self):
        return sqlite3.connect(self.db_file)

    def create_structure(self, conn):
        def col_desc_to_string(col_name, null, ref=None, col_type=None, converter=None):
            # Either column type or coverter must be specified.
            assert (col_type is None) != (converter is None)
            if converter is not None:
                col_type = converter.db_type()
            null = '' if null else ' NOT NULL'
            ref = 'FOREIGN KEY({}) REFERENCES {}({})'.format(col_name, *ref) if ref else None
            return '{} {}{}'.format(col_name, col_type, null), ref

        for table_name in self.tables:
            descs = []
            # References must go after *all* column declarations.
            refs = []
            for desc in self.desc_for_table(table_name):
                desc, ref = col_desc_to_string(**desc)
                descs.append(desc)
                if ref is not None: refs.append(ref)
            descs = ", ".join(descs)
            refs = ", ".join(refs)
            if refs:
                refs = ", " + refs
            cmd = "CREATE TABLE {}({}{})".format(table_name, descs, refs)
            conn.execute(cmd)
        conn.execute("PRAGMA jorunal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")

    def __insert(self, conn, table, data, **extra_data):
        table_desc = self.desc_for_table(table)
        converted_data = []
        for col_desc in table_desc:
            col_name = col_desc['col_name']
            col_data = data.get(col_name) or extra_data.get(col_name)
            if col_data is None:
                if col_desc['null']:
                    col_data = None
                else:
                    raise Exception("Missing non-nullable column value '{}'".format(col_name))
            converter = col_desc.get('converter')
            converted_data.append(converter.to_db(col_data) if converter else col_data)
        sql = "INSERT INTO {} VALUES ({})".format(table,
            ", ".join('?' for x in range(len(converted_data))))
        cursor = conn.execute(sql, converted_data)
        cursor.close()
        return cursor.lastrowid

    def __select(self, conn, table, col, value, orderby=None):
        cursor = conn.execute("SELECT rowid, * FROM {} WHERE {}=?{}".format(
            table, col, "ORDER BY {}".format(orderby) if orderby else ''),
            (value,))
        table_desc = self.desc_for_table(table)
        res = []
        rowids = []
        for result in cursor.fetchall():
            entry = {}
            for col_desc, col in zip(table_desc, result[1:]):
                if 'ref' not in col_desc:
                    if col is None:
                        assert col_desc['null']
                        continue
                    converter = col_desc.get('converter')
                    if converter:
                        col = converter.from_db(col)
                    entry[col_desc['col_name']] = col
            res.append(entry)
            rowids.append(result[0])
        return res, rowids

    def insert_command(self, conn, command):
        command_id = self.__insert(conn, 'command', command)
        for task in command['tasks']:
            task_id = self.__insert(conn, 'task', task, command_id=command_id)
            for session in task['sessions']:
                self.__insert(conn, 'session', session, task_id=task_id)
        return command_id

    def get_command(self, conn, rowid):
        assert rowid > 0
        commands, rowids = self.__select(conn, 'command', 'rowid', rowid)
        assert len(commands) in (0, 1)
        if len(commands) == 0:
            return None
        command = commands[0]
        tasks, task_row_ids = self.__select(conn, 'task', 'command_id', rowid)
        for task, task_id in zip(tasks, task_row_ids):
            sessions, session_row_ids = self.__select(conn, 'session', 'task_id', task_id, orderby='started')
            task['sessions'] = sessions
        command['tasks'] = tasks
        return command

class DatabaseInserter:
    class Quit: pass

    def __init__(self, database):
        self.database = database
        self.queue = Queue()
        self.thread = Thread(target=self.__worker_thread)
        self.thread.start()

    def __worker_thread(self):
        with self.database.get_connection() as conn:
            changed = False
            while True:
                try:
                    what = self.queue.get(timeout=2)
                    if what is self.Quit:
                        if changed:
                            conn.commit()
                        return
                    command_info, on_completion = what
                    command_id = self.database.insert_command(conn, command_info)
                    changed = True
                    on_completion(command_id)
                except Empty:
                    if changed:
                        conn.commit()
                        changed = False


    def async_insert(self, command_info, on_completion):
        self.queue.put((command_info, on_completion))

    def close(self):
        self.queue.put(self.Quit)
        self.thread.join()

   