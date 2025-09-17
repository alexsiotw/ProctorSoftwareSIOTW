import json
from http import HTTPStatus
from flask import render_template_string
from pusher import Pusher
import os

pusher = Pusher(
    app_id=os.environ['PUSHER_APP_ID'],
    key=os.environ['PUSHER_KEY'],
    secret=os.environ['PUSHER_SECRET'],
    cluster=os.environ['PUSHER_CLUSTER'],
    ssl=True
)

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
    <script src="https://js.pusher.com/8.2/pusher.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const pusher = new Pusher('{{ PUSHER_KEY }}', { cluster: '{{ PUSHER_CLUSTER }}' });
        let examId;
        let channel;

        document.getElementById('createExam').onclick = () => {
            fetch('/api/create_exam').then(res => res.json()).then(data => {
                examId = data.exam_id;
                document.getElementById('examControls').style.display = 'block';
                document.getElementById('examId').innerHTML = `Exam ID: ${examId} (Share with students)`;
                channel = pusher.subscribe(`exam-${examId}`);
                channel.bind('student_joined', (data) => updateStudentCard(data.studentId, 'Joined', 'status-active'));
                channel.bind('tab_change', (data) => updateStudentCard(data.studentId, 'Tab Changed', 'status-tab-changed'));
                channel.bind('screenshot', (data) => updateStudentCard(data.studentId, 'Active', 'status-active', data.screenshot, data.timestamp));
                channel.bind('audio_chunk', (data) => updateStudentCard(data.studentId, 'Active', 'status-active', null, data.timestamp, data.audio));
                channel.bind('recording_saved', (data) => {
                    document.getElementById('recordings').innerHTML += `<div class="alert alert-info">Recording saved: <a href="/api/download/${data.filename}" target="_blank">${data.filename}</a></div>`;
                });
                channel.bind('student_leave', (data) => updateStudentCard(data.studentId, 'Disconnected', 'status-disconnected'));
                channel.bind('status', (data) => console.log('Status:', data.msg));
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
            fetch('/api/teacher', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({examId, action: 'start_exam', options})
            });
            document.getElementById('endExam').style.display = 'inline-block';
        };

        document.getElementById('endExam').onclick = () => {
            fetch('/api/teacher', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({examId, action: 'end_exam'})
            });
            document.getElementById('endExam').style.display = 'none';
        };

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

def handler(event, context):
    try:
        if event['httpMethod'] == 'POST':
            data = json.loads(event.get('body', '{}'))
            from functions.db import update_exam_options
            if data['action'] == 'start_exam':
                update_exam_options(data['examId'], data['options'])
                pusher.trigger(f'exam-{data["examId"]}', 'exam_started', {'examId': data['examId']})
                pusher.trigger(f'exam-{data["examId"]}', 'options_push', data['options'])
                return {'statusCode': HTTPStatus.OK, 'body': json.dumps({'success': True})}
            elif data['action'] == 'end_exam':
                from functions.db import update_exam_options
                update_exam_options(data['examId'], {})
                pusher.trigger(f'exam-{data["examId"]}', 'exam_ended', {})
                return {'statusCode': HTTPStatus.OK, 'body': json.dumps({'success': True})}
        return {
            'statusCode': HTTPStatus.OK,
            'headers': {'Content-Type': 'text/html'},
            'body': render_template_string(TEACHER_HTML, PUSHER_KEY=os.environ['PUSHER_KEY'], PUSHER_CLUSTER=os.environ['PUSHER_CLUSTER'])
        }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
