import os
import sqlite3

from .compile_session import SessionResult

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
        return ConvertEnum

    session_table = [
        {'col_name': 'task_id'  , 'col_type': 'INTEGER', 'null': False,
            'ref': ('task', 'rowid')},
        {'col_name': 'hostname' , 'col_type': 'TEXT'   , 'null': False},
        {'col_name': 'port'     , 'col_type': 'TEXT'   , 'null': False},
        {'col_name': 'started'  , 'col_type': 'REAL'   , 'null': False},
        {'col_name': 'completed', 'col_type': 'REAL'   , 'null': False},
        {'col_name': 'result'   , 'col_type': 'INTEGER', 'null': False,
            'converter': convert_enum(SessionResult)}]

    @classmethod
    def desc_for_table(cls, table_name):
        return cls.__dict__[table_name + '_table']

    def __init__(self, scratch_dir=None):
        if scratch_dir is None:
            self.db_file = ':memory:'
        else:
            self.db_file = os.path.join(scratch_dir, 'build_info.db')
            try:
                os.remove(self.db_file)
            except FileNotFoundError:
                pass

    def get_connection(self):
        return sqlite3.connect(self.db_file)

    def create_structure(self, conn):
        def col_desc_to_string(col_name, col_type, null, ref=None, converter="currently unused"):
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

    def __insert(self, conn, table, data, **extra_data):
        table_desc = self.desc_for_table(table)
        sql = "INSERT INTO {} VALUES ({})".format(table,
            ", ".join('?' for x in range(len(table_desc))))
        converted_data = []
        for col_desc in table_desc:
            col_name = col_desc['col_name']
            col_data = data.get(col_name) or extra_data[col_name]
            converter = col_desc.get('converter')
            converted_data.append(converter.to_db(col_data) if converter else col_data)
        cursor = conn.execute(sql, converted_data)
        return cursor.lastrowid

    def __select(self, conn, table, col, value):
        cursor = conn.execute("SELECT rowid, * FROM {} WHERE {}=?".format(table, col), (value,))
        table_desc = self.desc_for_table(table)
        res = []
        rowids = []
        for result in cursor.fetchall():
            entry = {}
            for col_desc, col in zip(table_desc, result[1:]):
                if 'ref' not in col_desc:
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
            sessions, session_row_ids = self.__select(conn, 'session', 'task_id', task_id)
            task['sessions'] = sessions
        command['tasks'] = tasks
        return command
