"""Inspect one isolated deployment. Output never includes environment parameters."""
import argparse
import base64
import importlib.util
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

spec=importlib.util.spec_from_file_location('deploy',Path(__file__).with_name('deploy-wxcloud.py'))
deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)


def run(args):
    private=json.loads(args.private_file.read_text(encoding='utf-8'))
    client=deploy.DeploymentClient(args.appid_file,args.key_file)
    parameters={'EnvId':private['env_id'],'ServerName':private['service']}
    result=client.action('DescribeServerManageTask',parameters,private['region'])
    task=result.get('Task') or {}
    output={'service':private['service'],'deployment':task.get('Status'),'failure_reason':task.get('FailReason'),
        'steps':[{k:s.get(k) for k in ('Name','Status','FailReason')} for s in task.get('Steps',[])]}
    if args.build_log:
        versions=client.action('DescribeCloudBaseRunServer',{**parameters,'Offset':0,'Limit':100},private['region'])
        version=next((v for v in versions.get('VersionItems',[]) if v.get('VersionName')==task.get('VersionName')), {})
        log=client.action('DescribeCloudBaseRunBuildLog',{'EnvId':private['env_id'],
            'ServiceVersion':version.get('VersionName'),'BuildId':version.get('BuildId')},private['region'])
        text=log.get('Log',{}).get('Text','')
        for value in private.get('env_params',{}).values():
            if isinstance(value,str) and len(value)>5:text=text.replace(value,'[REDACTED]')
        text=re.sub(r'https?://\S+','[URL]',text)
        output['build_log_tail']=text[-6000:]
    try:
        token=base64.b64encode(('admin:'+private['admin_password']).encode()).decode()
        request=urllib.request.Request(private['origin']+'/api/cloud/status',headers={'Authorization':'Basic '+token})
        with urllib.request.urlopen(request,timeout=20) as response:output['runtime']=json.load(response)
    except urllib.error.HTTPError as error:output['http_status']=error.code
    except Exception as error:output['runtime_error']=type(error).__name__
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appid-file',type=Path,required=True)
    parser.add_argument('--key-file',type=Path,required=True)
    parser.add_argument('--private-file',type=Path,required=True)
    parser.add_argument('--build-log',action='store_true')
    try:run(parser.parse_args())
    except Exception as error:print(json.dumps({'ok':False,'error_type':type(error).__name__}));raise SystemExit(1)
