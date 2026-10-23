"""Explicitly transfer a selected account cache to the operator's own private cloud runtime."""
import argparse
import base64
import json
import sys
import tomllib
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud.account_auth import validate_cache, validate_model


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):raise RuntimeError('Credential transfer redirect refused')


def main(args):
    private=json.loads(args.private_file.read_text(encoding='utf-8'))
    origin=private['origin']
    from urllib.parse import urlsplit
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Expected the private deployment HTTPS origin')
    auth=json.loads(args.auth_file.read_text(encoding='utf-8-sig'));validate_cache(auth)
    model=None
    if args.config_file:model=validate_model(tomllib.loads(args.config_file.read_text(encoding='utf-8-sig')).get('model'))
    token=base64.b64encode(('admin:'+private['admin_password']).encode()).decode()
    opener=urllib.request.build_opener(NoRedirect)
    for endpoint,payload in [('import',{'auth':auth,'model':model}),('check',{})]:
        request=urllib.request.Request(origin+'/api/cloud/auth/'+endpoint,data=json.dumps(payload).encode(),
            headers={'Authorization':'Basic '+token,'Origin':origin,'Content-Type':'application/json'})
        with opener.open(request,timeout=30) as response:value=json.load(response)
        print(json.dumps({'operation':endpoint,'phase':value.get('phase'),'model':value.get('model')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-file',type=Path,required=True)
    parser.add_argument('--auth-file',type=Path,required=True,help='Explicitly authorized local ChatGPT auth.json; never packaged')
    parser.add_argument('--config-file',type=Path,help='Read only the model name from this local config.toml')
    try:main(parser.parse_args())
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,'http_status':getattr(error,'code',None)}))
        raise SystemExit(1)
