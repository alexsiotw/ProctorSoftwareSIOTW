import json
from flask import render_template_string
from pusher import Pusher
import os
from functions.db import get_exam_options, add_student

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
    <script src="/js/pusher.js"></script>
    <script>
        const pusher = new Pusher('{{ PUSHER_KEY }}', { cluster: '{{ PUSHER_CLUSTER }}' });
        const examId = '{{ exam_id }}';
        const studentId = '{{ student_id }}';
        let channel = pusher.subscribe(`exam-${examId}`);
        let options = {};
        let streams = {};
        let mediaRecorder;
        let audioRecorder;
        let recordedChunks = [];
        let chunkSize = 1024 * 1024;
        let screenshotInterval;

        channel.bind('options_push', (data) => {
            options = data;
            console.log('Received options:', options);
            const cameraCheckbox = document.getElementById('camera');
            const micCheckbox = document.getElementById('mic');
            const screenCheckbox = document.getElementById('screen');
            cameraCheckbox.checked = options.camera;
            micCheckbox.checked = options.mic;
            screenCheckbox.checked = options.screen;
            document.getElementById('optionsConfirm').style.display = 'block';
            document.getElementById('status').innerHTML = 'Please confirm proctoring options to start the exam.';
        });

        document.getElementById('confirmOptions').onclick = async () => {
            channel.trigger('client-options_confirmed', {examId, studentId});
            document.getElementById('optionsConfirm').style.display = 'none';
            document.getElementById('testIframe').style.display = 'block';
            await initMedia();
            document.getElementById('status').innerHTML = 'Exam Started - Do not switch tabs or leave the page!';
            if (options.record) mediaRecorder.start();
            if (options.mic) audioRecorder.start(10000);
            if (options.screen || options.camera) screenshotInterval = setInterval(captureScreenshot, 5000);
        };

        async function initMedia() {
            try {
                if (options.camera) streams.camera = await navigator.mediaDevices.getUserMedia({video: true});
                if (options.mic) {
                    streams.mic = await navigator.mediaDevices.getUserMedia({audio: true});
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
                        if (document.hidden) channel.trigger('client-tab_changed', {examId, studentId});
                    });
                }
                
                setInterval(() => channel.trigger('client-heartbeat', {examId, studentId}), 5000);
            } catch (err) {
                console.error('Media access error:', err);
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

            fetch('/api/upload_chunk', {method: 'POST', body: formData}).then(res => res.json()).then(data => {
                if (data.success && chunkIndex < totalChunks - 1) uploadChunk(blob, chunkIndex + 1);
            }).catch(err => console.error('Upload error:', err));
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
        exam_id = event['queryStringParameters']['examId']
        student_id = str(uuid.uuid4())[:8]
        add_student(student_id, exam_id)
        pusher.trigger(f'exam-{exam_id}', 'student_joined', {'studentId': student_id})
        return {'statusCode': 200, 'body': render_template_string(STUDENT_HTML, exam_id=exam_id, student_id=student_id, PUSHER_KEY=os.environ['PUSHER_KEY'], PUSHER_CLUSTER=os.environ['PUSHER_CLUSTER'])}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
