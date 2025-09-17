import json
from http import HTTPStatus
from werkzeug.utils import secure_filename
import boto3
import os
from functions.db import save_recording
from pusher import Pusher

pusher = Pusher(
    app_id=os.environ['PUSHER_APP_ID'],
    key=os.environ['PUSHER_KEY'],
    secret=os.environ['PUSHER_SECRET'],
    cluster=os.environ['PUSHER_CLUSTER'],
    ssl=True
)

s3_client = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
) if os.environ.get('AWS_ACCESS_KEY_ID') else None
BUCKET = os.environ.get('S3_BUCKET', 'proctor-recordings')

def handler(event, context):
    try:
        # Parse multipart form data
        from io import BytesIO
        from urllib.parse import parse_qs
        body = event['body']
        if event.get('isBase64Encoded'):
            body = base64.b64decode(body)
        boundary = event['headers']['content-type'].split('boundary=')[1]
        parts = body.split(b'--' + boundary.encode())
        form_data = {}
        chunk = None
        for part in parts:
            if b'Content-Disposition' in part:
                headers, content = part.split(b'\r\n\r\n', 1)
                headers = headers.decode()
                name_match = re.search(r'name="([^"]+)"', headers)
                if name_match:
                    name = name_match.group(1)
                    content = content.rstrip(b'\r\n--')
                    if name == 'chunk':
                        chunk = BytesIO(content)
                    else:
                        form_data[name] = content.decode()

        exam_id = form_data['examId']
        student_id = form_data['studentId']
        chunk_index = int(form_data['chunkIndex'])
        total_chunks = int(form_data['totalChunks'])
        filename = secure_filename(form_data['filename'])

        if s3_client:
            key = f"{exam_id}/{filename}.part{chunk_index}"
            s3_client.upload_fileobj(chunk, BUCKET, key)
            if chunk_index == total_chunks - 1:
                recording_id = save_recording(exam_id, student_id, filename)
                pusher.trigger(f'exam-{exam_id}', 'recording_saved', {'filename': filename, 'recording_id': recording_id})
        else:
            os.makedirs('recordings', exist_ok=True)
            filepath = os.path.join('recordings', filename)
            with open(filepath, 'ab') as f:
                f.seek(chunk_index * 1024 * 1024)
                chunk.seek(0)
                f.write(chunk.read())
            if chunk_index == total_chunks - 1:
                recording_id = save_recording(exam_id, student_id, filename)
                pusher.trigger(f'exam-{exam_id}', 'recording_saved', {'filename': filename, 'recording_id': recording_id})

        return {
            'statusCode': HTTPStatus.OK,
            'body': json.dumps({'success': True})
        }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
