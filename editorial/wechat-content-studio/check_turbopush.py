"""Read local TurboPush account metadata without logging its authentication token."""
import json
import sys
import urllib.request
from pathlib import Path
from studio import ROOT, write, now

def check():
    cfg = json.loads((Path.home()/'.TurboPush/mcp.json').read_text(encoding='utf-8-sig'))
    port = int(cfg['port'])
    if not 1 <= port <= 65535: raise ValueError('Invalid service port')
    auth = str(cfg['auth'])
    results = {}
    for name, endpoint in [('platforms','/platform/list?simple=true'),('accounts','/account/list?simple=true'),('logged_accounts','/account/logged?simple=true')]:
        req = urllib.request.Request(f'http://127.0.0.1:{port}'+endpoint, headers={'Authorization':auth})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        if data.get('code') != 200: raise RuntimeError('Local account query failed')
        def safe(value):
            if isinstance(value, list): return [safe(v) for v in value]
            if isinstance(value, dict):
                allowed = {'id','name','nickname','platName','platType','login','platform_id','platform','list','records','total','items','status','key','type','value','article','graph_text','video'}
                return {k:safe(v) for k,v in value.items() if k in allowed}
            return value
        results[name] = safe(data.get('data'))
    result = {'checked_at':now(),'local_service_reachable':True,**results,'browser_publish_not_invoked':True}
    write(ROOT/'state/turbopush-check.json',result)
    return result

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: print(json.dumps(check(),ensure_ascii=False,indent=2))
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,'message':'Local TurboPush probe failed; authentication was not logged'}));sys.exit(1)
