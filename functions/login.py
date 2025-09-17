import json
from http import HTTPStatus

TEACHER_USER = 'admin'
TEACHER_PASS = 'password'

def handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        if body.get('username') == TEACHER_USER and body.get('password') == TEACHER_PASS:
            return {
                'statusCode': HTTPStatus.OK,
                'body': json.dumps({'success': True, 'is_teacher': True})
            }
        return {
            'statusCode': HTTPStatus.OK,
            'body': json.dumps({'success': False})
        }
    except Exception as e:
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }
