import os
import uuid
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_change_me'
app.config['UPLOAD_FOLDER'] = 'recordings'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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

# Hardcoded auth
TEACHER_USER = 'admin'
TEACHER_PASS = 'password'

# HTML Templates
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
            <p class="mt-3">Student? Enter exam ID: <input id="examId" class="form-control d-inline w-auto" placeholder="Exam ID">
            <button onclick="window.location='/student?examId='+document.getElementById('examId').value" class="btn btn-secondary">Join Exam</button></p>
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
    <style>
        .student-card { margin-bottom: 20px; }
        .status-indicator { font-size: 0.9em; color: #fff; padding: 5px; border-radius: 5px; }
        .status-active { background-color: green; }
        .status-tab-changed { background-color: orange; }
        .status-disconnected { background-color: red; }
        .audio-player { max-width: 100%; }
    </style>
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
        <h3>Student Dashboard</h3>
        <div id="studentDashboard" class="row"></div>
        <div id="recordings" class="mt-3"></div>
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const socket = io();
        let examId;
        socket.on('connect', () => {
            console.log('Teacher connected to WebSocket');
            socket.emit('join_teacher', {examId});
        });

        document.getElementById('createExam').onclick = () => {
            fetch('/create_exam').then(res => res.json()).then(data => {
                examId = data.exam_id;
                document.getElementById('examControls').style.display = 'block';
                document.getElementById('examId').innerHTML = `Exam ID: ${examId} (Share with students)`;
                socket.emit('set_exam', {examId});
            });
        };

        document.getElementById('startExam').onclick = () => {
            const options = {
                camera: document.getElementById('camera').checked,
                mic: document.getElementById('mic').checked,
                screen: document.getElementById('screen').checked,
                tabDetect: document.getElementById('tabDetect').checked,
                record: document.getElementById('record').checked
            };
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
            updateStudentCard(data.studentId, 'Joined', 'status-active');
        });

        socket.on('tab_change', (data) => {
            updateStudentCard(data.studentId, 'Tab Changed', 'status-tab-changed');
        });

        socket.on('screenshot', (data) => {
            updateStudentCard(data.studentId, 'Active', 'status-active', data.screenshot, data.timestamp);
        });

        socket.on('audio_chunk', (data) => {
            updateStudentCard(data.studentId, 'Active', 'status-active', null, data.timestamp, data.audio);
        });

        socket.on('recording_saved', (data) => {
            document.getElementById('recordings').innerHTML += `<div class="alert alert-info">Recording saved: <a href="/download/${data.filename}" target="_blank">${data.filename}</a></div>`;
        });

        socket.on('student_leave', (data) => {
            updateStudentCard(data.studentId, 'Disconnected', 'status-disconnected');
        });

        socket.on('status', (data) => {
            console.log('Status:', data.msg);
        });

        function updateStudentCard(studentId, status, statusClass, screenshot = null, timestamp = null, audio = null) {
            let card = document.getElementById(`student-${studentId}`);
            if (!card) {
                card = document.createElement('div');
                card.id = `student-${studentId}`;
                card.className = 'col-md-4 student-card';
                document.getElementById('studentDashboard').appendChild(card);
            }
            card.innerHTML = `
                <div class="card">
                    <div class="card-header">Student ${studentId}</div>
                    <div class="card-body">
                        <p>Status: <span class="status-indicator ${statusClass}">${status}</span></p>
                        ${screenshot ? `<img src="data:image/png;base64,${screenshot}" class="card-img-top" alt="Screenshot" style="max-width: 100%;">` : ''}
                        ${audio ? `<audio class="audio-player" controls><source src="data:audio/webm;base64,${audio}" type="audio/webm"></audio>` : ''}
                        ${timestamp ? `<p>Last Update: ${timestamp}</p>` : ''}
                    </div>
                </div>`;
        }
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
    <div id="optionsConfirm" class="alert alert-info" style="display:none;">
        <h3>Proctoring Options</h3>
        <form id="proctoringForm">
            <div class="form-check">
                <input type="checkbox" class="form-check-input" id="camera" disabled>
                <label class="form-check-label" for="camera">Camera</label>
            </div>
            <div class="form-check">
                <input type="checkbox" class="form-check-input" id="mic" disabled>
                <label class="form-check-label" for="mic">Mic</label>
            </div>
            <div class="form-check">
                <input type="checkbox" class="form-check-input" id="screen" disabled>
                <label class="form-check-label" for="screen">Screen Share</label>
            </div>
            <button type="button" id="confirmOptions" class="btn btn-success mt-3">Start Exam</button>
        </form>
    </div>
    <iframe id="testIframe" src="https://docs.google.com/forms/d/e/hU5tRVMcBS9GX8Mu5/viewform?embedded=true" width="100%" height="600" style="display:none; border:none;"></iframe>
    <div id="status" class="alert alert-warning mt-3">Waiting for exam to start...</div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const socket = io();
        const urlParams = new URLSearchParams(window.location.search);
        const examId = urlParams.get('examId');
        const studentId = '{{ student_id }}';
        if (!examId) {
            alert('No Exam ID provided');
            window.location = '/login';
            return;
        }

        function joinExam() {
            console.log('Joining exam:', examId, studentId);
            socket.emit('join_student', {examId, studentId});
        }

        socket.on('connect', () => {
            console.log('Student connected to WebSocket');
            joinExam();
        });

        socket.on('connect_error', (err) => {
            console.error('WebSocket connection error:', err);
            document.getElementById('status').innerHTML = 'Connection error. Retrying...';
            setTimeout(joinExam, 3000);
        });

        socket.on('options_push', (data) => {
            console.log('Received options:', data);
            const options = data;
            const cameraCheckbox = document.getElementById('camera');
            const micCheckbox = document.getElementById('mic');
            const screenCheckbox = document.getElementById('screen');
            cameraCheckbox.checked = options.camera;
            micCheckbox.checked = options.mic;
            screenCheckbox.checked = options.screen;
            document.getElementById('optionsConfirm').style.display = 'block';
            document.getElementById('status').innerHTML = 'Please confirm proctoring options to start the exam.';
        });

        let options = {};
        let streams = {};
        let mediaRecorder;
        let audioRecorder;
        let recordedChunks = [];
        let audioChunks = [];
        let chunkSize = 1024 * 1024; // 1MB
        let currentChunk = 0;
        let totalChunks = 0;
        let screenshotInterval;

        document.getElementById('confirmOptions').onclick = async () => {
            console.log('Start Exam clicked');
            socket.emit('options_confirmed', {examId, studentId});
            document.getElementById('optionsConfirm').style.display = 'none';
            document.getElementById('testIframe').style.display = 'block';
            await initMedia();
            document.getElementById('status').innerHTML = 'Exam Started - Do not switch tabs or leave the page!';
            if (options.record && (streams.camera || streams.mic || streams.screen)) mediaRecorder.start();
            if (options.mic) audioRecorder.start(10000); // Send audio every 10s
            if (options.screen || options.camera) screenshotInterval = setInterval(captureScreenshot, 5000);
        };

        async function initMedia() {
            try {
                if (options.camera) {
                    streams.camera = await navigator.mediaDevices.getUserMedia({video: true});
                    console.log('Camera access granted');
                }
                if (options.mic) {
                    streams.mic = await navigator.mediaDevices.getUserMedia({audio: true});
                    console.log('Mic access granted');
                    const audioStream = new MediaStream(streams.mic.getAudioTracks());
                    audioRecorder = new MediaRecorder(audioStream, {mimeType: 'audio/webm'});
                    audioRecorder.ondataavailable = async (event) => {
                        if (event.data.size > 0) {
                            const reader = new FileReader();
                            reader.onload = () => {
                                const audio = reader.result.split(',')[1];
                                socket.emit('audio_chunk', {examId, studentId, audio, timestamp: new Date().toISOString()});
                            };
                            reader.readAsDataURL(event.data);
                        }
                    };
                }
                if (options.screen) {
                    streams.screen = await navigator.mediaDevices.getDisplayMedia({video: true});
                    console.log('Screen share access granted');
                }
                
                const tracks = [];
                if (streams.camera) tracks.push(...streams.camera.getTracks());
                if (streams.mic) tracks.push(...streams.mic.getTracks());
                if (streams.screen) tracks.push(...streams.screen.getTracks());
                
                if (options.record && tracks.length > 0) {
                    const combined = new MediaStream(tracks);
                    mediaRecorder = new MediaRecorder(combined, {mimeType: 'video/webm'});
                    mediaRecorder.ondataavailable = handleChunk;
                    mediaRecorder.onstop = finalizeUpload;
                    console.log('MediaRecorder initialized');
                }
                
                if (options.tabDetect) {
                    document.addEventListener('visibilitychange', () => {
                        if (document.hidden) socket.emit('tab_changed', {examId, studentId});
                    });
                }
                
                setInterval(() => socket.emit('heartbeat', {examId, studentId}), 5000);
            } catch (err) {
                console.error('Media access error:', err);
                alert('Media access denied: ' + err.message);
                document.getElementById('status').innerHTML = 'Error: Media access denied. Please allow permissions and refresh.';
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
            }).catch(err => {
                console.error('Upload error:', err);
                alert('Upload failed: ' + err.message);
            });
        }

        async function captureScreenshot() {
            try {
                const canvas = await html2canvas(document.body, {scale: 0.5});
                const dataUrl = canvas.toDataURL('image/png');
                const screenshot = dataUrl.split(',')[1];
                socket.emit('screenshot', {examId, studentId, screenshot, timestamp: new Date().toISOString()});
            } catch (err) {
                console.error('Screenshot failed:', err);
            }
        }

        window.onbeforeunload = () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
            if (audioRecorder && audioRecorder.state === 'recording') audioRecorder.stop();
            if (screenshotInterval) clearInterval(screenshotInterval);
            socket.emit('student_leave', {examId, studentId});
        };

        socket.on('exam_ended', () => {
            alert('Exam ended by teacher.');
            if (mediaRecorder) mediaRecorder.stop();
            if (audioRecorder) audioRecorder.stop();
            if (screenshotInterval) clearInterval(screenshotInterval);
            window.location = '/login';
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string(LOGIN_HTML)
    data = request.json
    if data['username'] == TEACHER_USER and data['password'] == TEACHER_PASS:
        session['is_teacher'] = True
        return jsonify({'success': True, 'is_teacher': True})
    return jsonify({'success': False})

@app.route('/teacher')
def teacher():
    if not session.get('is_teacher'):
        return redirect(url_for('login'))
    return render_template_string(TEACHER_HTML)

@app.route('/student')
def student():
    exam_id = request.args.get('examId')
    if not exam_id:
        return redirect(url_for('login'))
    student_id = str(uuid.uuid4())[:8]
    return render_template_string(STUDENT_HTML, student_id=student_id)

@app.route('/create_exam')
def create_exam():
    if not session.get('is_teacher'):
        return jsonify({'error': 'Unauthorized'}, 401)
    exam_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO exams (id, active, created_at) VALUES (?, 0, ?)", (exam_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    app.logger.info(f'Exam created: {exam_id}')
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

    try:
        with open(filepath, 'ab') as f:
            f.seek(chunk_index * (1024 * 1024))
            chunk.save(f)

        if chunk_index == total_chunks - 1:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT INTO recordings (id, exam_id, student_id, filename, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                      (str(uuid.uuid4())[:8], exam_id, student_id, secure_name, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            socketio.emit('recording_saved', {'filename': secure_name}, room=exam_id)
            app.logger.info(f'Recording saved: {secure_name} for student {student_id} in exam {exam_id}')
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'Upload chunk failed: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download/<filename>')
def download(filename):
    if not session.get('is_teacher'):
        return jsonify({'error': 'Unauthorized'}, 401)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('join_teacher')
def on_join_teacher(data):
    exam_id = data.get('examId')
    if exam_id:
        join_room(exam_id)
        emit('status', {'msg': 'Teacher joined'}, room=exam_id)
        app.logger.info(f'Teacher joined exam: {exam_id}')

@socketio.on('set_exam')
def set_exam(data):
    global exam_id
    exam_id = data['examId']
    app.logger.info(f'Exam set: {exam_id}')

@socketio.on('join_student')
def on_join_student(data):
    exam_id = data['examId']
    student_id = data['studentId']
    join_room(exam_id)
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO students (id, exam_id, joined_at) VALUES (?, ?, ?)",
              (student_id, exam_id, datetime.now().isoformat()))
    c.execute("SELECT options FROM exams WHERE id=?", (exam_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    
    app.logger.info(f'Student {student_id} joined exam {exam_id}')
    emit('student_joined', {'studentId': student_id}, room=exam_id)
    if row and row[0]:
        import json
        options = json.loads(row[0])
        emit('options_push', options, room=exam_id)
        app.logger.info(f'Pushed options to exam {exam_id}: {options}')
    else:
        app.logger.warning(f'No options found for exam {exam_id}')

@socketio.on('start_exam')
def start_exam(data):
    exam_id = data['examId']
    options = data['options']
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    import json
    c.execute("UPDATE exams SET options=?, active=1 WHERE id=?", (json.dumps(options), exam_id))
    conn.commit()
    conn.close()
    emit('exam_started', {'examId': exam_id}, room=exam_id)
    emit('options_push', options, room=exam_id)
    app.logger.info(f'Exam {exam_id} started with options: {options}')

@socketio.on('end_exam')
def end_exam(data):
    exam_id = data['examId']
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE exams SET active=0 WHERE id=?", (exam_id,))
    conn.commit()
    conn.close()
    emit('exam_ended', {}, room=exam_id)
    app.logger.info(f'Exam {exam_id} ended')

@socketio.on('options_confirmed')
def options_confirmed(data):
    emit('status', {'msg': f'Student {data["studentId"]} confirmed'}, room=data['examId'])
    app.logger.info(f'Student {data["studentId"]} confirmed options for exam {data["examId"]}')

@socketio.on('tab_changed')
def tab_changed(data):
    emit('tab_change', {'studentId': data['studentId']}, room=data['examId'])
    app.logger.info(f'Student {data["studentId"]} changed tab in exam {data["examId"]}')

@socketio.on('heartbeat')
def heartbeat(data):
    emit('status', {'msg': f'Student {data["studentId"]} active'}, room=data['examId'])

@socketio.on('screenshot')
def screenshot(data):
    emit('screenshot', data, room=data['examId'])
    app.logger.info(f'Screenshot received from student {data["studentId"]} in exam {data["examId"]}')

@socketio.on('audio_chunk')
def audio_chunk(data):
    emit('audio_chunk', data, room=data['examId'])
    app.logger.info(f'Audio chunk received from student {data["studentId"]} in exam {data["examId"]}')

@socketio.on('student_leave')
def student_leave(data):
    exam_id = data['examId']
    student_id = data['studentId']
    leave_room(exam_id)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE id=? AND exam_id=?", (student_id, exam_id))
    conn.commit()
    conn.close()
    emit('student_leave', {'studentId': student_id}, room=exam_id)
    app.logger.info(f'Student {student_id} left exam {exam_id}')

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
