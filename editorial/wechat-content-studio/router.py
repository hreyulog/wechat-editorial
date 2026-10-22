import json
import sys
from studio import attach_link, review, status

sys.stdout.reconfigure(encoding='utf-8')
request = json.load(sys.stdin)
try:
    action = request['action']
    if action == 'link': result = attach_link(request['id'], request['version'], request['url'], request['message_id'])
    elif action == 'approve': result = review(request['id'], request['version'], request['message_id'])
    else: result = status(request.get('id'))
    print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False))
except Exception as error:
    print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
