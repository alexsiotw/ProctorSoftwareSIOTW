Python 3.13.7 (tags/v3.13.7:bcee1c3, Aug 14 2025, 14:15:11) [MSC v.1944 64 bit (AMD64)] on win32
Enter "help" below or click "Help" above for more information.
# Complete Anti-Cheat Exam Proctoring System
# Enhanced version with:
# - SQLite database for persistence (exams, students, recordings metadata).
# - Chunked video upload to avoid base64 limits (JS sends blobs in chunks).
# - Periodic screenshot emission for real-time screen proctoring (if screen share enabled).
# - Basic authentication (hardcoded for simplicity: teacher 'admin'/pass, students no login).
# - Improved UI with Bootstrap.
# - End-exam functionality.
# - No mobile optimizations.
#
# Setup:
# 1. pip install flask flask-socketio eventlet gunicorn sqlite3 html2canvas (wait, html2canvas is JS lib, add via CDN).
# 2. Run locally: gunicorn -k eventlet -w 1 app:app
# 3. For Render.com deployment: See guide below.
# 4. Replace GOOGLE_FORM_URL with your embedded form URL.
# 5. Recordings saved in /recordings/ dir (create it).

import os
import uuid
import base64
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_change_me'
app.config['UPLOAD_FOLDER'] = 'recordings'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# SQLite setup
DB_FILE = 'proctoring.db'
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS exams
                 (id TEXT PRIMARY KEY, options TEXT, active INTEGER, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS students
                 (id TEXT PRIMARY KEY, exam_id TEXT, joined_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recordings
                 (id TEXT PRIMARY KEY, exam_id TEXT, student_id TEXT, filename TEXT, uploaded_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Hardcoded auth (use JWT or OAuth in prod)
TEACHER_USER = 'admin'
TEACHER_PASS = 'password'

# HTML Templates (with Bootstrap for better UI)
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="container mt-5">
    <div class="row justify-content-center">
        <div class="col-md-4">
            <h2>Proctoring System Login</h2>
            <form id="loginForm">
                <div class="mb-3"><input type="text" class="form-control" id="username" placeholder="Username"></div>
                <div class="mb-3"><input type="password" class="form-control" id="password" placeholder="Password"></div>
                <button type="submit" class="btn btn-primary w-100">Login</button>
            </form>
            <div id="message" class="mt-3"></div>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').onsubmit = async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const res = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})});
            const data = await res.json();
            if (data.success) {
                if (data.is_teacher) window.location = '/teacher';
                else window.location = '/student';
            } else {
                document.getElementById('message').innerHTML = '<div class="alert alert-danger">Invalid credentials</div>';
            }
        };
    </script>
</body>
</html>
"""

TEACHER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Teacher Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="container mt-5">
    <h1>Exam Proctoring Dashboard</h1>
    <button id="createExam" class="btn btn-success mb-3">Create New Exam</button>
    <div id="examControls" style="display:none;">
        <button id="startExam" class="btn btn-primary">Start Exam</button>
        <button id="endExam" class="btn btn-danger" style="display:none;">End Exam</button>
        <div class="form-check mt-3">
            <label class="form-check-label"><input type="checkbox" class="form-check-input" id="camera"> Camera</label>
        </div>
        <div class="form-check"><label class="form-check-label"><input type="checkbox" class="form-check-input" id="mic"> Mic</label></div>
        <div class="form-check"><label class="form-check-label"><input type="checkbox" class="form-check-input" id="screen"> Screen Share</label></div>
        <div class="form-check"><label class="form-check-label"><input type="checkbox" class="form-check-input" id="tabDetect"> Detect Tab Change</label></div>
        <div class="form-check"><label class="form-check-label"><input type="checkbox" class="form-check-input" id="record"> Record</label></div>
        <div id="examId" class="alert alert-info mt-3"></div>
        <div id="students" class="mt-3"></div>
        <div id="recordings" class="mt-3"></div>
        <div id="proctorFeed" class="row mt-3"></div> <!-- For screenshots -->
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const socket = io();
        let examId;
        socket.on('connect', () => socket.emit('join_teacher', examId));

        document.getElementById('createExam').onclick = () => {
            fetch('/create_exam').then(res => res.json()).then(data => {
                examId = data.exam_id;
                document.getElementById('examControls').style.display = 'block';
                document.getElementById('examId').innerHTML = `Exam ID: ${examId} (Share with students)`;
                socket.emit('set_exam', examId);
            });
        };

        document.getElementById('startExam').onclick = () => {
            const options = {camera: document.getElementById('camera').checked, mic: document.getElementById('mic').checked,
                            screen: document.getElementById('screen').checked, tabDetect: document.getElementById('tabDetect').checked,
                            record: document.getElementById('record').checked};
            socket.emit('start_exam', {examId, options});
            document.getElementById('endExam').style.display = 'inline-block';
        };

        document.getElementById('endExam').onclick = () => {
            socket.emit('end_exam', {examId});
            document.getElementById('endExam').style.display = 'none';
        };

        socket.on('exam_started', (data) => {
            document.getElementById('examId').innerHTML += ' - ACTIVE';
        });

        socket.on('student_joined', (data) => {
            document.getElementById('students').innerHTML += `<div class="alert alert-success">Student ${data.studentId} joined</div>`;
        });

        socket.on('tab_change', (data) => {
            document.getElementById('students').innerHTML += `<div class="alert alert-warning">Student ${data.studentId} changed tab!</div>`;
        });

        socket.on('screenshot', (data) => {
            const col = document.createElement('div');
            col.className = 'col-md-4';
            col.innerHTML = `<div class="card"><img src="data:image/png;base64,${data.screenshot}" class="card-img-top" alt="Screenshot from ${data.studentId}"><div class="card-body"><p class="card-text">${data.studentId} - ${data.timestamp}</p></div></div>`;
            document.getElementById('proctorFeed').appendChild(col);
        });

        socket.on('recording_saved', (data) => {
            document.getElementById('recordings').innerHTML += `<div class="alert alert-info">Recording saved: <a href="/download/${data.filename}" target="_blank">${data.filename}</a></div>`;
        });
    </script>
</body>
</html>
"""

STUDENT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Student Exam</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="container mt-5">
    <h1>Online Exam</h1>
    <div id="optionsConfirm" class="alert alert-info" style="display:none;"></div>
    <button id="confirmOptions" class="btn btn-success" style="display:none;">Confirm and Start Exam</button>
    <iframe id="testIframe" src="https://docs.google.com/forms/YOUR_GOOGLE_FORM_ID/viewform?embedded=true" width="100%" height="600" style="display:none; border:none;"></iframe>
    <div id="status" class="alert alert-warning mt-3"></div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const socket = io();
        const urlParams = new URLSearchParams(window.location.search);
        const examId = urlParams.get('examId');
        const studentId = '{{ student_id }}';
        if (!examId) { alert('No Exam ID provided'); return; }
        socket.emit('join_student', {examId, studentId});

        let options = {};
        let streams = {};
        let mediaRecorder;
        let recordedChunks = [];
        let chunkSize = 1024 * 1024; // 1MB chunks
        let currentChunk = 0;
        let totalChunks = 0;
        let screenshotInterval;

        socket.on('options_push', (data) => {
            options = data;
            let html = '<h3>Proctoring Options (Confirm to Start):</h3><ul>';
            for (let key in options) if (options[key]) html += `<li>${key.charAt(0).toUpperCase() + key.slice(1).replace(/([A-Z])/g, ' $1')}</li>`;
            html += '</ul>';
            document.getElementById('optionsConfirm').innerHTML = html;
            document.getElementById('optionsConfirm').style.display = 'block';
            document.getElementById('confirmOptions').style.display = 'block';
        });

        document.getElementById('confirmOptions').onclick = async () => {
            socket.emit('options_confirmed', {examId, studentId});
            document.getElementById('confirmOptions').style.display = 'none';
            document.getElementById('testIframe').style.display = 'block';
            await initMedia();
            document.getElementById('status').innerHTML = 'Exam Started - Do not switch tabs or leave the page!';
            if (options.record) mediaRecorder.start();
            if (options.screen) screenshotInterval = setInterval(captureScreenshot, 5000);
        };

        async function initMedia() {
            try {
                if (options.camera) streams.camera = await navigator.mediaDevices.getUserMedia({video: true});
                if (options.mic) streams.mic = await navigator.mediaDevices.getUserMedia({audio: true});
                if (options.screen) streams.screen = await navigator.mediaDevices.getDisplayMedia({video: true});
                
                const tracks = [];
                if (streams.camera) tracks.push(...streams.camera.getTracks());
                if (streams.mic) tracks.push(...streams.mic.getTracks());
                if (streams.screen) tracks.push(...streams.screen.getTracks());
                
                if (options.record && tracks.length > 0) {
                    const combined = new MediaStream(tracks);
                    mediaRecorder = new MediaRecorder(combined, {mimeType: 'video/webm'});
                    mediaRecorder.ondataavailable = handleChunk;
                    mediaRecorder.onstop = finalizeUpload;
                }
                
                if (options.tabDetect) {
                    document.addEventListener('visibilitychange', () => {
                        if (document.hidden) socket.emit('tab_changed', {examId, studentId});
                    });
                }
                
                setInterval(() => socket.emit('heartbeat', {examId, studentId}), 5000);
            } catch (err) {
                alert('Media access denied: ' + err.message);
            }
        }

        function handleChunk(event) {
            if (event.data.size > 0) recordedChunks.push(event.data);
        }

        function finalizeUpload() {
            const blob = new Blob(recordedChunks, {type: 'video/webm'});
            totalChunks = Math.ceil(blob.size / chunkSize);
            uploadChunk(blob, 0);
        }

        function uploadChunk(blob, chunkIndex) {
            const start = chunkIndex * chunkSize;
            const end = Math.min(start + chunkSize, blob.size);
            const chunk = blob.slice(start, end);
            const formData = new FormData();
            formData.append('examId', examId);
            formData.append('studentId', studentId);
            formData.append('chunk', chunk);
            formData.append('chunkIndex', chunkIndex);
            formData.append('totalChunks', totalChunks);
            formData.append('filename', `${examId}_${studentId}_${Date.now()}.webm`);

            fetch('/upload_chunk', {method: 'POST', body: formData}).then(res => res.json()).then(data => {
                if (data.success && chunkIndex < totalChunks - 1) {
                    uploadChunk(blob, chunkIndex + 1);
                }
            });
        }

        async function captureScreenshot() {
            const canvas = await html2canvas(document.body);
            const dataUrl = canvas.toDataURL('image/png');
            const screenshot = dataUrl.split(',')[1];
            socket.emit('screenshot', {examId, studentId, screenshot, timestamp: new Date().toISOString()});
        }

        window.onbeforeunload = () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
            if (screenshotInterval) clearInterval(screenshotInterval);
            socket.emit('student_leave', {examId, studentId});
        };

        socket.on('exam_ended', () => {
            alert('Exam ended by teacher.');
            if (mediaRecorder) mediaRecorder.stop();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    if data['username'] == TEACHER_USER and data['password'] == TEACHER_PASS:
        session['is_teacher'] = True
        return jsonify({'success': True, 'is_teacher': True})
    else:
        session['is_teacher'] = False
        return jsonify({'success': True, 'is_teacher': False})  # Students no pass needed

@app.route('/teacher')
def teacher():
    if not session.get('is_teacher'):
        return redirect(url_for('login'))
    return render_template_string(TEACHER_HTML)

@app.route('/student')
def student():
    exam_id = request.args.get('examId')
    if not exam_id:
        return 'Invalid Exam ID', 400
    student_id = str(uuid.uuid4())[:8]
    return render_template_string(STUDENT_HTML, student_id=student_id)

@app.route('/create_exam')
def create_exam():
    exam_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO exams (id, active, created_at) VALUES (?, 0, ?)", (exam_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'exam_id': exam_id})

@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    exam_id = request.form['examId']
    student_id = request.form['studentId']
    chunk = request.files['chunk']
    chunk_index = int(request.form['chunkIndex'])
    total_chunks = int(request.form['totalChunks'])
    filename = request.form['filename']
    secure_name = secure_filename(filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_name)

    with open(filepath, 'ab') as f:
        f.seek(chunk_index * int(request.form.get('chunkSize', 1024*1024)))
        chunk.save(f)

    if chunk_index == total_chunks - 1:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO recordings (id, exam_id, student_id, filename, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                  (str(uuid.uuid4())[:8], exam_id, student_id, secure_name, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        socketio.emit('recording_saved', {'filename': secure_name}, room=exam_id)

    return jsonify({'success': True})

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('join_teacher')
def on_join_teacher(data):
    global exam_id  # From set_exam
    exam_id = data.get('examId')
    join_room(exam_id)
    emit('status', {'msg': 'Joined'})

@socketio.on('set_exam')
def set_exam(data):
    global exam_id
    exam_id = data['examId']

@socketio.on('join_student')
def on_join_student(data):
    exam_id = data['examId']
    student_id = data['studentId']
    join_room(exam_id)
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO students (id, exam_id, joined_at) VALUES (?, ?, ?)",
              (student_id, exam_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    emit('student_joined', {'studentId': student_id}, room=exam_id)
    
    c.execute("SELECT options FROM exams WHERE id=?", (exam_id,))
    row = c.fetchone()
    if row and row[0]:
        options = eval(row[0])  # Unsafe, use JSON in prod
        emit('options_push', options, room=socketio.sid)  # To this student

@socketio.on('start_exam')
def start_exam(data):
    exam_id = data['examId']
    options = data['options']
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE exams SET options=?, active=1 WHERE id=?", (str(options), exam_id))
    conn.commit()
    conn.close()
    emit('exam_started', {'examId': exam_id}, room=exam_id)
    # Push to all students in room

@socketio.on('end_exam')
def end_exam(data):
...     exam_id = data['examId']
...     conn = sqlite3.connect(DB_FILE)
...     c = conn.cursor()
...     c.execute("UPDATE exams SET active=0 WHERE id=?", (exam_id,))
...     conn.commit()
...     conn.close()
...     emit('exam_ended', {}, room=exam_id)
... 
... @socketio.on('options_confirmed')
... def options_confirmed(data):
...     emit('status', {'msg': f'Student {data["studentId"]} confirmed'}, room=data['examId'])
... 
... @socketio.on('tab_changed')
... def tab_changed(data):
...     emit('tab_change', {'studentId': data['studentId']}, room=data['examId'])
... 
... @socketio.on('heartbeat')
... def heartbeat(data):
...     pass  # Ack
... 
... @socketio.on('screenshot')
... def screenshot(data):
...     emit('screenshot', data, room=data['examId'])
... 
... @socketio.on('student_leave')
... def student_leave(data):
...     exam_id = data['examId']
...     student_id = data['studentId']
...     leave_room(exam_id)
...     conn = sqlite3.connect(DB_FILE)
...     c = conn.cursor()
...     c.execute("DELETE FROM students WHERE id=? AND exam_id=?", (student_id, exam_id))
...     conn.commit()
...     conn.close()
... 
... if __name__ == '__main__':
