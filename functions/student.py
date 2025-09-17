import json
from http import HTTPStatus
from flask import render_template_string
import uuid
import os
from functions.db import get_exam_options, add_student
from pusher import Pusher

pusher = Pusher(
    app_id=os.environ['PUSHER_APP_ID'],
    key=os.environ['PUSHER_KEY'],
    secret=os.environ['PUSHER_SECRET'],
    cluster=os.environ['PUSHER_CLUSTER'],
    ssl=True
)

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
    <script src="https://js.pusher.com/8.2/pusher.min.js"></script>
    <script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const pusher = new Pusher('{{ PUSHER_KEY }}', { cluster: '{{ PUSHER_CLUSTER }}', forceTLS: true });
        const examId = '{{ exam_id }}';
        const studentId = '{{ student_id }}';
        const channel = pusher.subscribe(`exam-${examId}`);
        let options = {};
        let streams = {};
        let mediaRecorder;
        let audioRecorder;
        let recordedChunks = [];
        let audioChunks = [];
        let chunkSize = 1024 * 1024;
        let screenshotInterval;

        function joinExam() {
            console.log('Joining exam:', examId, studentId);
            fetch('/api/student', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({examId, studentId, action: 'join'})
            });
        }

        pusher.connection.bind('connected', () => {
            console.log('Pusher connected');
            joinExam();
        });

        pusher.connection.bind('error', (err) => {
            console.error('Pusher connection error:', err);
            document.getElementById('status').innerHTML = 'Connection error. Retrying...';
            setTimeout(joinExam, 3000);
        });

        channel.bind('options_push', (data) => {
            console.log('Received options:', data);
            options = data;
            document.getElementById('camera').checked = options.camera;
            document.getElementById('mic').checked = options.mic;
            document.getElementById('screen').checked = options.screen;
            document.getElementById('optionsConfirm').style.display = 'block';
            document.getElementById('status').innerHTML = 'Please confirm proctoring options to start the exam.';
        });

        document.getElementById('confirmOptions').onclick = async () => {
            console.log('Start Exam clicked');
            channel.trigger('client-options_confirmed', {examId, studentId});
            document.getElementById('optionsConfirm').style.display = 'none';
            document.getElementById('testIframe').style.display = 'block';
            await initMedia();
            document.getElementById('status').innerHTML = 'Exam Started - Do not switch tabs or leave the page!';
            if (options.record && (streams.camera || streams.mic || streams.screen)) mediaRecorder.start();
            if (options.mic) audioRecorder.start(10000);
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
                                channel.trigger('client-audio_chunk', {examId, studentId, audio, timestamp: new Date().toISOString()});
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
                if (streams.camera) tracks.push(...streams.camera.getVideoTracks());
                if (streams.mic) tracks.push(...streams.mic.getAudioTracks());
                if (streams.screen) tracks.push(...streams.screen.getVideoTracks());
                
                if (options.record && tracks.length > 0) {
                    const combined = new MediaStream(tracks);
                    mediaRecorder = new MediaRecorder(combined, {mimeType: 'video/webm'});
                    mediaRecorder.ondataavailable = handleChunk;
                    mediaRecorder.onstop = finalizeUpload;
                    console.log('MediaRecorder initialized');
                }
                
                if (options.tabDetect) {
                    document.addEventListener('visibilitychange', () => {
                        if (document.hidden) channel.trigger('client-tab_changed', {examId, studentId});
                    });
                }
                
                setInterval(() => channel.trigger('client-heartbeat', {examId, studentId}), 5000);
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
            const totalChunks = Math.ceil(blob.size / chunkSize);
            uploadChunk(blob, 0, totalChunks);
        }

        function uploadChunk(blob, chunkIndex, totalChunks) {
            const start = chunkIndex * chunkSize;
            const end = Math.min(start + chunkSize, blob.size);
            const chunk = blob.slice(start, end);
            const formData = new FormData();
            formData.append('examId', examId);
            formData.append('studentId', studentId);
            formData.append('chunk', chunk, `chunk-${chunkIndex}`);
            formData.append('chunkIndex', chunkIndex);
            formData.append('totalChunks', totalChunks);
            formData.append('filename', `${examId}_${studentId}_${Date.now()}.webm`);

            fetch('/api/upload_chunk', {method: 'POST', body: formData}).then(res => res.json()).then(data => {
                if (data.success && chunkIndex < totalChunks - 1) {
                    uploadChunk(blob, chunkIndex + 1, totalChunks);
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
                channel.trigger('client-screenshot', {examId, studentId, screenshot, timestamp: new Date().toISOString()});
            } catch (err) {
                console.error('Screenshot failed:', err);
            }
        }

        window.onbeforeunload = () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
            if (audioRecorder && audioRecorder.state === 'recording') audioRecorder.stop();
            if (screenshotInterval) clearInterval(screenshotInterval);
            channel.trigger('client-student_leave', {examId, studentId});
        };

        channel.bind('exam_ended', () => {
            alert('Exam ended by teacher.');
            if (mediaRecorder) mediaRecorder.stop();
            if (audioRecorder) audioRecorder.stop();
            if (screenshotInterval) clearInterval(screenshotInterval);
            window.location = '/';
        });
    </script>
</body>
</html>
"""

def handler(event, context):
    try:
        if event['httpMethod'] == 'POST':
            data = json.loads(event.get('body', '{}'))
            if data.get('action') == 'join':
                exam_id = data['examId']
                student_id = data['studentId']
                add_student(student_id, exam_id)
                options = get_exam_options(exam_id)
                pusher.trigger(f'exam-{exam_id}', 'student_joined', {'studentId': student_id})
                if options:
                    pusher.trigger(f'exam-{exam_id}', 'options_push', options)
                return {'statusCode': HTTPStatus.OK, 'body': json.dumps({'success': True})}
        else:
            exam_id = event['queryStringParameters'].get('examId')
            if not exam_id:
                return {
                    'statusCode': HTTPStatus.BAD_REQUEST,
                    'body': json.dumps({'error': 'No examId provided'})
                }
            student_id = str(uuid.uuid4())[:8]
            return {
                'statusCode': HTTPStatus.OK,
                'headers': {'Content-Type': 'text/html'},
                'body': render_template_string(STUDENT_HTML, exam_id=exam_id, student_id=student_id, PUSHER_KEY=os.environ['PUSHER_KEY'], PUSHER_CLUSTER=os.environ['PUSHER_CLUSTER'])
            }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
