import sys
sys.path.append('..')

from time import time

from Manager.database import Database
from Manager.compile_session import SessionResult

def test_create_structure():
    db = Database()
    with db.get_connection() as conn:
        db.create_structure(conn)

def test_insert_and_select():
    session = {
        'hostname': 'localhost',
        'port': '12345',
        'started': time(),
        'completed': time() + 10,
        'result': SessionResult.success}

    task = {
        'source': 'asdf.cpp',
        'pch_file': 'fdsa.pch',
        'sessions': [session]}

    command = {
        'command': 'compile',
        'tasks': [task]}

    db = Database()
    conn = db.get_connection()
    db.create_structure(conn)
    with conn:
        id = db.insert_command(conn, command)
        assert db.get_command(conn, id) == command


