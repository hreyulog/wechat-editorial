"""Synchronous durability boundary. No cloud behavior unless explicitly enabled."""
import json
import os
import urllib.request
from pathlib import Path


def call(operation, **values):
    if not os.environ.get('EDITORIAL_CLOUD'):
        return None
    request = urllib.request.Request('http://127.0.0.1:8790/'+operation,
        data=json.dumps(values, ensure_ascii=False).encode(), headers={
            'Content-Type':'application/json', 'Authorization':'Bearer '+os.environ['EDITORIAL_LOCAL_TOKEN']})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)
    except Exception:
        raise RuntimeError('Cloud persistence unavailable; operation stopped before local commit') from None


def persist(path, data):
    return call('write', path=str(Path(path).resolve()), data=data)


if __name__ == '__main__':
    import sys
    value = json.load(sys.stdin)
    result = call(value.pop('operation'), **value)
    print(json.dumps(result))
