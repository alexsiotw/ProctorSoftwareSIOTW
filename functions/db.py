import os
import json
from datetime import datetime
import uuid
from faunadb import FaunaClient, query as q
from faunadb.objects import Ref
import sqlite3

USE_FAUNA = bool(os.environ.get('FAUNA_SECRET'))

if USE_FAUNA:
    client = FaunaClient(secret=os.environ['FAUNA_SECRET'])
    # Create collections if not exist (run once)
    try:
        client.query(q.Create(q.Collection('exams'), {'name': 'exams'}))
        client.query(q.Create(q.Index('exams_by_id'), {'name': 'exams_by_id', 'source': q.Collection('exams'), 'terms': [{'field': ['data', 'id']}] }))
        client.query(q.Create(q.Collection('students'), {'name': 'students'}))
        client.query(q.Create(q.Index('students_by_id'), {'name': 'students_by_id', 'source': q.Collection('students'), 'terms': [{'field': ['data', 'id']}] }))
        client.query(q.Create(q.Collection('recordings'), {'name': 'recordings'}))
    except:
        pass  # Collections exist
else:
    DB_FILE = 'proctoring.db'
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS exams (id TEXT PRIMARY KEY, options TEXT, active INTEGER, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, exam_id TEXT, joined_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recordings (id TEXT PRIMARY KEY, exam_id TEXT, student_id TEXT, filename TEXT, uploaded_at TEXT)''')
    conn.commit()
    conn.close()

def create_exam(exam_id):
    if USE_FAUNA:
        client.query(q.Create(q.Collection('exams'), {'data': {'id': exam_id, 'active': 0, 'created_at': datetime.now().isoformat()}}))
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO exams (id, active, created_at) VALUES (?, 0, ?)", (exam_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def get_exam_options(exam_id):
    if USE_FAUNA:
        result = client.query(q.Get(q.Match(q.Index('exams_by_id'), exam_id)))
        return json.loads(result['data'].get('options', '{}'))
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT options FROM exams WHERE id=?", (exam_id,))
        row = c.fetchone()
        conn.close()
        return json.loads(row[0]) if row and row[0] else {}

def update_exam_options(exam_id, options):
    options_json = json.dumps(options)
    if USE_FAUNA:
        client.query(q.Update(q.Select('Ref', q.Get(q.Match(q.Index('exams_by_id'), exam_id))), {'data': {'options': options_json, 'active': 1}}))
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE exams SET options=?, active=1 WHERE id=?", (options_json, exam_id))
        conn.commit()
        conn.close()

def add_student(student_id, exam_id):
    if USE_FAUNA:
        client.query(q.Create(q.Collection('students'), {'data': {'id': student_id, 'exam_id': exam_id, 'joined_at': datetime.now().isoformat()}}))
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO students (id, exam_id, joined_at) VALUES (?, ?, ?)", (student_id, exam_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def save_recording(exam_id, student_id, filename):
    if USE_FAUNA:
        client.query(q.Create(q.Collection('recordings'), {'data': {'exam_id': exam_id, 'student_id': student_id, 'filename': filename, 'uploaded_at': datetime.now().isoformat()}}))
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO recordings (id, exam_id, student_id, filename, uploaded_at) VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4())[:8], exam_id, student_id, filename, datetime.now().isoformat()))
        conn.commit()
        conn.close()
