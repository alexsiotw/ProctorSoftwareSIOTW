import json
from flask import request
from pusher import Pusher
import os

pusher = Pusher(
    app_id=os.environ['PUSHER_APP_ID'],
    key=os.environ['PUSHER_KEY'],
    secret=os.environ['PUSHER_SECRET'],
    cluster=os.environ['PUSHER_CLUSTER'],
    ssl=True
)

TEACHER_USER = 'admin'
TEACHER_PASS = 'password'

def handler(event, context):
    try:
        body = json.loads(event['body'])
        if body['username'] == TEACHER_USER and body['password'] == TEACHER_PASS:
            return {'statusCode': 200, 'body': json.dumps({'success': True, 'is_teacher': True})}
        return {'statusCode': 200, 'body': json.dumps({'success': False})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
