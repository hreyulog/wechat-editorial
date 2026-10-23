"""Deploy an isolated Bot service using the published @wxcloud/cli transport.

No desktop state or login cache is uploaded. Secrets are environment parameters,
never Docker build arguments. Existing services are read only for DB/COS settings.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import secrets
import subprocess
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inventory',ROOT/'scripts/inspect-wxcloud.py')
inventory=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory)
MUTATIONS={'EstablishCloudBaseRunServerWx','UpdateServerBaseConfig','SubmitServerRelease','DeleteCloudBaseRunServerVersion'}
READS=inventory.READ_ACTIONS|{'DescribeCloudBaseBuildService','DescribeServerManageTask',
    'DescribeCloudBaseRunBuildLog','DescribeCloudBaseRunProcessLog','SearchClsLog'}


class DeploymentClient(inventory.Client):
    def action(self,name,data,region='ap-shanghai'):
        if name not in READS|MUTATIONS:raise ValueError('Operation is outside deployment scope')
        if name in MUTATIONS and not (data.get('ServerName') or data.get('ServiceName','')).startswith('editorial-'):
            raise ValueError('Only dedicated editorial services may be changed')
        if name=='DeleteCloudBaseRunServerVersion' and (data.get('IsDeleteServer') is not False or data.get('IsDeleteImage') is not False
                or not data.get('VersionName','').startswith(data['ServerName']+'-')):
            raise ValueError('Retiring a version must preserve its service and rollback image')
        response=self.request('apihttpagent',{'action':name,'postdata':json.dumps(data),
            'region':region,'service':'tcb','version':'2018-06-08'})
        result=json.loads(response['content'])['Response']
        if result.get('Error'):
            self.last_error=result['Error']
            raise RuntimeError('Cloud API '+name+' error: '+str(result['Error'].get('Code','unknown')))
        return result


def package(secret_values, dockerfile=None):
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    output=io.BytesIO()
    unicode_sources={}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in filter(None,names):
            path=Path(name)
            if any(part in ('node_modules','state','jobs','outbox','.venv','__pycache__','sessions') for part in path.parts):
                raise RuntimeError('Runtime file in tracked build context')
            if name=='.env' or name.endswith('/aws.env'):raise RuntimeError('Credential path in source')
            data=dockerfile.encode() if name=='Dockerfile' and dockerfile else (ROOT/path).read_bytes()
            if any(value and len(value)>8 and value.encode() in data for value in secret_values):
                raise RuntimeError('Credential bytes in source; deployment stopped')
            if name.isascii():archive.writestr(name,data)
            else:unicode_sources[name]=base64.b64encode(data).decode()
        # The platform's unzip/build handoff corrupts UTF-8 filenames. Carry only
        # ASCII entry names and restore original UTF-8 paths inside the image.
        archive.writestr('cloud/unicode-sources.json',json.dumps(unicode_sources,ensure_ascii=True))
    return output.getvalue()


def deploy(args):
    client=DeploymentClient(args.appid_file,args.key_file)
    credentials={name:(args.credentials/name).read_text(encoding='utf-8-sig').strip()
        for name in ('appid.txt','appsecret.txt','botid.txt','qiyesecret.txt')}
    if credentials['appid.txt']!=client.appid:raise ValueError('Official account differs from CLI account')
    namespace=hashlib.sha256(credentials['botid.txt'].encode()).hexdigest()[:8]
    service='editorial-'+namespace
    environments=client.action('DescribeWxCloudBaseRunEnvs',{'WxAppId':client.appid})['EnvList']
    environment=next(e for e in environments if e['EnvId']==args.env_id)
    env_id=environment['EnvId'];region=environment['Region']
    output=args.private_output;output.mkdir(parents=True,exist_ok=True)
    receipt_path=output/'deployment-private.json'
    if receipt_path.exists():
        private=json.loads(receipt_path.read_text(encoding='utf-8'))
        if private['service']!=service or private['env_id']!=env_id:raise ValueError('Deployment namespace changed')
    else:
        private={'service':service,'env_id':env_id,'region':region,
            'admin_password':secrets.token_urlsafe(32),'master_key':base64.b64encode(secrets.token_bytes(32)).decode()}
        receipt_path.write_text(json.dumps(private,indent=2),encoding='utf-8');receipt_path.chmod(0o600)
    servers=client.action('DescribeCloudBaseRunServers',{'EnvId':env_id,'Limit':100,'Offset':0},region)
    if not any(s['ServerName']==service for s in servers.get('CloudBaseRunServerSet',[])):
        client.action('EstablishCloudBaseRunServerWx',{'EnvId':env_id,'ServiceName':service,
            'IsPublic':True,'OpenAccessTypes':['MINIAPP','PUBLIC']},region)
        print(json.dumps({'phase':'service_created','service':service}),flush=True)
    domain=client.action('DescribeCloudBaseRunServiceDomain',{'EnvId':env_id,'ServiceName':service},region)['DefaultPublicDomain']
    if not domain.startswith('https://'):domain='https://'+domain
    private['origin']=domain
    source=client.action('DescribeServiceBaseConfig',{'EnvId':env_id,'ServerName':args.settings_source},region)['ServiceBaseConfig']
    params=source.get('EnvParams') or '{}';params=json.loads(params) if isinstance(params,str) else params
    params={key:params[key] for key in ('COS_BUCKET','COS_REGION','MYSQL_ADDRESS','MYSQL_USERNAME','MYSQL_PASSWORD')}
    params.update(EDITORIAL_CLOUD='1',EDITORIAL_PUBLIC_ORIGIN=domain,
        EDITORIAL_ADMIN_PASSWORD=private['admin_password'],EDITORIAL_MASTER_KEY=private['master_key'],
        WECOM_BOT_ID=credentials['botid.txt'],WECOM_BOT_SECRET=credentials['qiyesecret.txt'],
        WECHAT_APPID=credentials['appid.txt'],WECHAT_APPSECRET=credentials['appsecret.txt'],
        WXCLOUD_APPID=client.appid,WXCLOUD_CLI_KEY=client.key,
        CODEX_TIMEOUT_SECONDS='14400',WECOM_PRIVATE_MESSAGES='all',PORT='8080')
    if args.openai_key_file:
        params['OPENAI_API_KEY']=args.openai_key_file.read_text(encoding='utf-8-sig').strip()
    if args.model_config_file:
        import sys
        sys.path.insert(0,str(ROOT))
        from cloud.model_config import validate
        model=validate(json.loads(args.model_config_file.read_text(encoding='utf-8-sig')))
        params.update(EDITORIAL_MODEL_API_KEY=model['api_key'],EDITORIAL_MODEL_BASE_URL=model['base_url'],CODEX_MODEL=model['model'])
    private['env_params']=params
    receipt_path.write_text(json.dumps(private,indent=2),encoding='utf-8')
    client.action('UpdateServerBaseConfig',{'WxAppId':client.appid,'EnvId':env_id,'ServerName':service,
        'Conf':{'EnvId':env_id,'ServerName':service,'Cpu':2,'Mem':4,'MinNum':1,'MaxNum':1,'Port':8080,'InitialDelaySeconds':30,
            'PolicyType':'','PolicyThreshold':0,'PolicyDetails':[{'PolicyType':'cpu','PolicyThreshold':70}],
            'LogType':'none','EnvParams':json.dumps(params),'OpenAccessTypes':['MINIAPP','PUBLIC'],
            'HasDockerfile':True,'BuildDir':'.','Dockerfile':'Dockerfile'}},region)
    dockerfile=None
    if args.base_version:
        if not args.base_version.startswith(service+'-'):raise ValueError('Base image must belong to this isolated service')
        detail=client.action('DescribeCloudBaseRunServerVersion',{'EnvId':env_id,'ServerName':service,'VersionName':args.base_version},region)
        image=detail.get('ImageUrl','')
        if not image.startswith('ccr.ccs.tencentyun.com/') or any(c.isspace() for c in image):raise ValueError('Unexpected cloud image registry')
        dockerfile=f'''FROM {image}
USER root
RUN if ! command -v nginx; then apt-get update && apt-get install -y --no-install-recommends nginx openssl xvfb x11vnc websockify novnc openbox dbus-x11 libwebkit2gtk-4.1-0 libayatana-appindicator3-1 && rm -rf /var/lib/apt/lists/*; fi
COPY cloud/install_turbopush.py /tmp/install_turbopush.py
RUN if [ ! -x /opt/turbopush/turbopush ]; then python3 /tmp/install_turbopush.py; fi
RUN python3 -c 'import qrcode' || pip install --no-cache-dir 'qrcode[pil]==8.2'
COPY --chown=editorial:editorial . /app
RUN python3 /app/cloud/restore_sources.py
USER editorial
RUN touch /tmp/editorial.htpasswd && nginx -t -c /app/cloud/nginx.conf
WORKDIR /app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "cloud.runtime"]
'''
    archive=package(list(credentials.values())+[client.key,private['admin_password'],private['master_key'],params['MYSQL_PASSWORD']],dockerfile)
    build=client.action('DescribeCloudBaseBuildService',{'EnvId':env_id,'ServiceName':service},region)
    target=urllib.parse.urlsplit(build['UploadUrl'])
    if target.scheme!='https' or not (target.hostname.endswith('.myqcloud.com') or target.hostname=='cloudbaserun-code-cos.cloudbase.net'):
        raise ValueError('Unexpected package upload host')
    request=urllib.request.Request(build['UploadUrl'],data=archive,method='PUT',headers={'Content-Type':'application/zip'})
    with urllib.request.build_opener(inventory.NoRedirect).open(request,timeout=180) as response:
        if response.status not in (200,201,204):raise RuntimeError('Package upload failed')
    result=client.action('SubmitServerRelease',{'ServerName':service,'EnvId':env_id,'WxAppId':client.appid,
        'DeployType':'package','ReleaseType':'FULL','HasDockerfile':True,'BuildDir':'.','Dockerfile':'Dockerfile',
        'Port':8080,'VersionRemark':'isolated editorial cloud runtime',
        'PackageName':build['PackageName'],'PackageVersion':build['PackageVersion']},region)
    private['last_release']=result
    receipt_path.write_text(json.dumps(private,indent=2),encoding='utf-8')
    print(json.dumps({'phase':'build_submitted','service':service,'origin':domain,'source_bytes':len(archive),
        'old_service_changed':False,'password_file':str(receipt_path)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appid-file',type=Path,required=True)
    parser.add_argument('--key-file',type=Path,required=True)
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--private-output',type=Path,required=True)
    parser.add_argument('--env-id',required=True)
    parser.add_argument('--settings-source',default='express-ulck')
    parser.add_argument('--openai-key-file',type=Path)
    parser.add_argument('--model-config-file',type=Path,help='Private JSON with base_url/model/api_key for a Responses API provider')
    parser.add_argument('--base-version',help='Reuse the verified runtime image of this same service; do not rebuild large unchanged dependencies')
    args=parser.parse_args()
    try:deploy(args)
    except Exception as error:
        # Do not dump HTTP request objects or platform error text containing env parameters.
        message=str(error) if type(error) is RuntimeError else type(error).__name__
        print(json.dumps({'phase':'deployment_failed','error':message},ensure_ascii=False));raise SystemExit(1)
