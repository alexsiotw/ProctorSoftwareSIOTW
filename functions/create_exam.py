import json
from http import HTTPStatus
import uuid
from functions.db import create_exam

def handler(event, context):
    try:
        exam_id = str(uuid.uuid4())[:8]
        create_exam(exam_id)
        return {
            'statusCode': HTTPStatus.OK,
            'body': json.dumps({'exam_id': exam_id})
        }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
