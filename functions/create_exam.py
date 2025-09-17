import json
import uuid
from functions.db import create_exam
from pusher import Pusher
import os

pusher = Pusher(
    app_id=os.environ['PUSHER_APP_ID'],
    key=os.environ['PUSHER_KEY'],
    secret=os.environ['PUSHER_SECRET'],
    cluster=os.environ['PUSHER_CLUSTER'],
    ssl=True
)

def handler(event, context):
    try:
        exam_id = str(uuid.uuid4())[:8]
        create_exam(exam_id)
        return {'statusCode': 200, 'body': json.dumps({'exam_id': exam_id})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
