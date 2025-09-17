import json
from http import HTTPStatus
import boto3
import os

s3_client = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
) if os.environ.get('AWS_ACCESS_KEY_ID') else None
BUCKET = os.environ.get('S3_BUCKET', 'proctor-recordings')

def handler(event, context):
    try:
        filename = event['pathParameters']['filename']
        if s3_client:
            key = filename
            url = s3_client.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=3600)
            return {
                'statusCode': HTTPStatus.FOUND,
                'headers': {'Location': url},
                'body': ''
            }
        else:
            filepath = os.path.join('recordings', filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    content = f.read()
                return {
                    'statusCode': HTTPStatus.OK,
                    'headers': {'Content-Type': 'video/webm', 'Content-Disposition': f'attachment; filename="{filename}"'},
                    'body': base64.b64encode(content).decode(),
                    'isBase64Encoded': True
                }
            else:
                return {
                    'statusCode': HTTPStatus.NOT_FOUND,
                    'body': json.dumps({'error': 'File not found'})
                }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
