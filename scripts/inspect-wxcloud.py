"""Read-only WeChat CloudRun inventory using the official @wxcloud/cli 2.3.3 transport.

Reference: lib/api/base.js and lib/api/cloudapiDirect.js in the published CLI.
Credentials are read from files, never passed as command-line values or logged.
"""
import argparse
import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

READ_ACTIONS = {'DescribeWxCloudBaseRunEnvs', 'DescribeCloudBaseRunServers', 'DescribeCloudBaseRunServiceDomain',
                'DescribeServiceBaseConfig', 'DescribeCloudBaseRunServer', 'DescribeCloudBaseRunServerVersion',
                'DescribeWxCloudBaseRunDBClusterDetail'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError('Official CLI API redirect refused')


class Client:
    def __init__(self, appid_path, key_path):
        self.appid = appid_path.read_text(encoding='utf-8-sig').strip()
        self.key = key_path.read_text(encoding='utf-8-sig').strip()
        if not re.fullmatch(r'wx[0-9a-f]{16}', self.appid) or not self.key or '\n' in self.key or '\r' in self.key:
            raise ValueError('AppID or CLI private key file is malformed')
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, endpoint, data):
        if endpoint not in ('getqbaseinfo', 'apihttpagent'):
            raise ValueError('Endpoint is outside the read-only inspection entrypoints')
        query = urllib.parse.urlencode({'autodev':1, 'appid':self.appid})
        request = urllib.request.Request('https://servicewechat.com/wxa-dev-qbase/'+endpoint+'?'+query,
            data=json.dumps(data).encode(), headers={'Content-Type':'application/json',
                'X-CloudRunCli-Robot':str(random.randint(1,30)), 'X-CloudRunCli-Key':self.key})
        with self.opener.open(request, timeout=40) as response:
            raw = response.read(2*1024*1024+1)
        if len(raw) > 2*1024*1024:
            raise RuntimeError('Response exceeded inspection limit')
        result = json.loads(raw)
        code = result.get('base_resp', {}).get('ret')
        if code != 0:
            # Raw platform errors can include request data; return the code only.
            raise RuntimeError('WeChat CloudRun CLI authentication/API error: '+str(code))
        return result

    def action(self, name, data, region=''):
        if name not in READ_ACTIONS:
            raise ValueError('Cloud mutation is not allowed by this inventory script')
        response = self.request('apihttpagent', {'action':name, 'postdata':json.dumps(data),
            'region':region, 'service':'tcb', 'version':'2018-06-08'})
        result = json.loads(response['content'])['Response']
        if result.get('Error'):
            raise RuntimeError('Cloud API error: '+str(result['Error'].get('Code', 'unknown')))
        return result


def inspect(client):
    client.request('getqbaseinfo', {'appid':client.appid})
    result = client.action('DescribeWxCloudBaseRunEnvs', {'WxAppId':client.appid})
    environments = []
    for environment in result.get('EnvList', []):
        env_id = environment['EnvId']
        region = environment.get('Region', '')
        record = {key:environment.get(key) for key in ('Alias','EnvId','Region','Status','CreateTime')}
        servers = client.action('DescribeCloudBaseRunServers', {'EnvId':env_id,'Limit':100,'Offset':0}, region)
        record['services'] = []
        for service in servers.get('CloudBaseRunServerSet', []):
            item = {key:service.get(key) for key in ('ServerName','Status','CreatedTime','UpdatedTime')}
            domain = client.action('DescribeCloudBaseRunServiceDomain', {'EnvId':env_id,'ServiceName':service['ServerName']}, region)
            item['domain'] = domain.get('DefaultPublicDomain')
            item['access_types'] = domain.get('AccessTypes', [])
            record['services'].append(item)
        database = client.action('DescribeWxCloudBaseRunDBClusterDetail', {'EnvId':env_id}, region)
        record['resources'] = {'object_storage_configured':bool(environment.get('Storages')),
                               'mysql_cluster_present':bool(database.get('DbClusterId')),
                               'mysql_status':database.get('DbInfo', {}).get('Status'),
                               'mysql_public_access':database.get('DbInfo', {}).get('IsOpenPubNetAccess')}
        environments.append(record)
    return {'checked_at':datetime.now(timezone.utc).isoformat(), 'credentials_accepted':True,
            'environments':environments,'cloud_resources_changed':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appid-file', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = inspect(Client(args.appid_file,args.key_file))
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        # Only our own fixed errors are printable; avoid urllib's request/headers.
        message = str(error) if type(error) is RuntimeError else 'Cloud inventory failed: '+type(error).__name__
        print(json.dumps({'ok':False,'error':message,'cloud_resources_changed':False},ensure_ascii=False))
        raise SystemExit(1)
