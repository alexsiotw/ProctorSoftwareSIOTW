from flask import send_from_directory
import os
import boto3

s3_client = boto3.client('s3', aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'), aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'))
BUCKET = os.environ.get('S3_BUCKET', 'proctor-recordings')

def handler(event, context):
    try:
        filename = event['pathParameters']['filename']
        if 'AWS_ACCESS_KEY_ID' in os.environ:
            key = f"{filename}"
            response = s3_client.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=3600)
            return {'statusCode': 302, 'headers': {'Location': response}, 'body': ''}
        else:
            return send_from_directory('recordings', filename)
    except Exception as e:
        return {'statusCode': 404, 'body': json.dumps({'error': 'File not found'})}
