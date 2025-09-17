import json
from flask import request
from werkzeug.utils import secure_filename
import boto3
import os
from functions.db import save_recording

s3_client = boto3.client('s3', aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'), aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'))
BUCKET = os.environ.get('S3_BUCKET', 'proctor-recordings')

def handler(event, context):
    try:
        form_data = request.form
        exam_id = form_data['examId']
        student_id = form_data['studentId']
        chunk = request.files['chunk']
        chunk_index = int(form_data['chunkIndex'])
        total_chunks = int(form_data['totalChunks'])
        filename = secure_filename(form_data['filename'])

        # Upload chunk to S3 (or local fallback)
        if 'AWS_ACCESS_KEY_ID' in os.environ:
            key = f"{exam_id}/{filename}.part{chunk_index}"
            s3_client.upload_fileobj(chunk, BUCKET, key)
            if chunk_index == total_chunks - 1:
                # Combine parts if needed, but for simplicity, save metadata
                save_recording(exam_id, student_id, filename)
                pusher.trigger(f'exam-{exam_id}', 'recording_saved', {'filename': filename})
        else:
            # Local fallback (not persistent on Netlify)
            filepath = os.path.join('recordings', filename)
            with open(filepath, 'ab') as f:
                f.seek(chunk_index * 1024 * 1024)
                chunk.save(f)
            if chunk_index == total_chunks - 1:
                save_recording(exam_id, student_id, filename)
                pusher.trigger(f'exam-{exam_id}', 'recording_saved', {'filename': filename})

        return {'statusCode': 200, 'body': json.dumps({'success': True})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
