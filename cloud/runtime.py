"""Container supervisor: private durability endpoint, public authenticated workbench."""
import importlib.util
import json
import os
import secrets
import signal
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cloud.store import ROOT, Store
from cloud import desktop
from cloud.model_config import provider_toml
from cloud.account_auth import validate_cache, validate_model, safe_failure, account_network_probe

os.environ['EDITORIAL_CLOUD']='1'
os.environ['EDITORIAL_LOCAL_TOKEN']=secrets.token_urlsafe(32)
studio=ROOT/'editorial/wechat-content-studio'
bot=ROOT/'editorial/wecom-bot-local'
status={'phase':'initializing','mysql':False,'cos':False,'restored_files':0}
store=None
child=None
login_process=None
login_state={'phase':'not_started'}
auth_guard=threading.Lock()
auth_check={'phase':'not_started'}


def model_busy():
    production=bot/'state/production.json'
    if production.exists() and json.loads(production.read_text()).get('phase')=='processing':return True
    for path in (bot/'state/inbox').glob('*.json'):
        if json.loads(path.read_text(encoding='utf-8')).get('status') in ('running','replying'):
            return True
    return False


def import_account_auth(data):
    """Private admin endpoint, only called after an explicit operator cache selection."""
    if not store or not status['mysql']:raise ValueError('Storage is not ready')
    if not isinstance(data,dict):raise ValueError('JSON object required')
    raw=validate_cache(data.get('auth'));model=validate_model(data.get('model'))
    with auth_guard:
        if model_busy() or auth_check.get('phase')=='checking' or (login_process and login_process.poll() is None):
            raise ValueError('Wait for the current task or login before replacing account credentials')
        if os.environ.get('EDITORIAL_MODEL_API_KEY') or os.environ.get('OPENAI_API_KEY'):
            raise ValueError('This installation already uses a separate API provider')
        store.secret('codex_auth',raw)
        home=Path(os.environ['CODEX_HOME']);target=home/'auth.json';temp=home/'auth.import.tmp'
        temp.write_bytes(raw);temp.chmod(0o600);temp.replace(target)
        if model:
            store.secret('codex_account_model',model.encode());os.environ['CODEX_MODEL']=model
            (home/'config.toml').write_text('model = '+json.dumps(model)+'\n',encoding='utf-8')
            (home/'config.toml').chmod(0o600)
        login_state.clear();login_state.update(phase='authenticated',method='operator_import')
        auth_check.clear();auth_check.update(phase='not_started')
    return {'phase':'authenticated','method':'operator_import','model':model}


def check_account_auth():
    """One fixed read-only model turn. No publication, messaging or user-chosen command."""
    with auth_guard:
        if auth_check.get('phase')=='checking':return dict(auth_check)
        if not store or model_busy():raise ValueError('Wait for storage and an idle worker')
        home=Path(os.environ['CODEX_HOME']);target=home/'auth.json'
        if not target.exists():raise ValueError('Account is not logged in')
        auth=json.loads(target.read_text());validate_cache(auth)
        auth_check.clear();auth_check.update(phase='checking')
        def run():
            network={}
            try:
                network=account_network_probe();auth_check['network']=network
                args=['codex','exec','--skip-git-repo-check','--sandbox','read-only','--ephemeral',
                    '-c','approval_policy="never"','--json']
                if os.environ.get('CODEX_MODEL'):args+=['--model',os.environ['CODEX_MODEL']]
                args+=['Reply with exactly CLOUD_CODEX_OK. Do not call tools or inspect files.']
                result=subprocess.run(args,cwd='/tmp',env=os.environ,capture_output=True,text=True,timeout=90)
                success=False
                for line in result.stdout.splitlines():
                    try:
                        value=json.loads(line);item=value.get('item',{})
                        if item.get('type')=='agent_message' and item.get('text','').strip()=='CLOUD_CODEX_OK':success=True
                    except (ValueError,TypeError):pass
                auth_check.clear();auth_check.update(phase='verified' if result.returncode==0 and success else 'failed',exit_code=result.returncode)
                auth_check['network']=network
                if auth_check['phase']=='failed':auth_check['error']=safe_failure(result.stderr+'\n'+result.stdout,auth)
                store.secret('codex_auth',target.read_bytes())
            except subprocess.TimeoutExpired as error:
                details='\n'.join(v.decode(errors='replace') if isinstance(v,bytes) else v or '' for v in (error.stderr,error.stdout))
                auth_check.clear();auth_check.update(phase='failed',error='Model authentication check timed out after 90 seconds',details=safe_failure(details,auth),network=network)
            except Exception as error:
                auth_check.clear();auth_check.update(phase='failed',error_type=type(error).__name__)
        threading.Thread(target=run,daemon=True).start()
        return dict(auth_check)


def cloud_login():
    global login_process
    if not store or not status['mysql']:return {'phase':'storage_not_ready'}
    if login_process and login_process.poll() is None:return dict(login_state)
    login_state.clear();login_state.update(phase='starting')
    login_process=subprocess.Popen(['codex','login','--device-auth'],stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,env=os.environ)
    def collect():
        errors=[]
        log=Path('/tmp/editorial-codex-login.log').open('w',encoding='utf-8')
        for line in login_process.stdout:
            line=re.sub(r'\x1b\[[0-9;]*m','',line)
            log.write(line);log.flush()
            if re.search(r'error|failed|forbidden|denied',line,re.I):
                sanitized=re.sub(r'https?://\S+','[authorization endpoint]',line).strip()
                for name in ('WECOM_BOT_SECRET','WECHAT_APPSECRET','WXCLOUD_CLI_KEY','EDITORIAL_MASTER_KEY','EDITORIAL_ADMIN_PASSWORD','OPENAI_API_KEY'):
                    if os.environ.get(name):sanitized=sanitized.replace(os.environ[name],'[REDACTED]')
                errors.append(sanitized[:500])
            match=re.search(r'https://(?:auth\.openai\.com|chatgpt\.com)/[a-zA-Z0-9/_.-]+',line)
            if match:login_state['url']=match[0]
            match=re.search(r'\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b',line)
            if match:login_state['code']=match[0];login_state['phase']='waiting_for_user'
        code=login_process.wait();log.close()
        auth=Path(os.environ['CODEX_HOME'])/'auth.json'
        if code==0 and auth.exists():
            try:store.secret('codex_auth',auth.read_bytes());login_state.clear();login_state['phase']='authenticated'
            except Exception:login_state.clear();login_state['phase']='persistence_failed'
        else:login_state.clear();login_state.update(phase='login_failed',exit_code=code,error='\n'.join(errors[-3:]))
    threading.Thread(target=collect,daemon=True).start()
    return dict(login_state)


class Durability(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        try:
            if not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+os.environ['EDITORIAL_LOCAL_TOKEN']):
                self.send_error(403);return
            length=int(self.headers.get('Content-Length',0))
            if length<0 or length>16*1024*1024:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(length))
            if store is None:raise RuntimeError('Storage not ready')
            if self.path=='/write':result={'ok':True,'local_only':not store.write(data['path'],data['data'])}
            elif self.path=='/fence':store.fence();result={'ok':True}
            elif self.path=='/checkpoint':result={'ok':True,'files':store.checkpoint()}
            else:self.send_error(404);return
            raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except Exception:
            self.send_error(503,'Persistence unavailable')


def cloud_status():
    result=dict(status)
    for name,field in [('connectivity.json','bot'),('binding-challenge.json','binding_challenge')]:
        path=bot/'state'/name
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            result[field]={key:value[key] for key in ('phase','authenticated','socket_connected','updated_at','phrase','received_messages','last_message','last_error') if key in value}
    binding_path=bot/'state/binding.json'
    binding=json.loads(binding_path.read_text()) if binding_path.exists() else {}
    result['group_bound']=bool(binding.get('chatid'))
    if result.get('stage')=='bot' and result.get('phase')=='waiting_for_group_binding' and result['group_bound']:
        result['phase']='running'
    result['private_messages']=binding.get('private_messages','disabled')
    production=bot/'state/production.json'
    if production.exists():result['worker']={'phase':json.loads(production.read_text()).get('phase')}
    result['codex_authenticated']=bool(os.environ.get('EDITORIAL_MODEL_API_KEY') or os.environ.get('OPENAI_API_KEY')) or (Path(os.environ['CODEX_HOME'])/'auth.json').exists()
    result['codex_login']=dict(login_state)
    result['codex_check']=dict(auth_check)
    result['turbopush']=dict(desktop.turbo_status)
    return result


def start_worker():
    global store,child
    try:
        candidate=Store()
        status['stage']='mysql_lease'
        while not candidate.acquire():
            status['phase']='waiting_for_previous_container';time.sleep(10)
        store=candidate;status['mysql']=True
        status['stage']='restore'
        status['restored_files']=store.restore()
        # A real private COS round trip is mandatory even when the installation is empty.
        probe=ROOT/'cloud/sessions/storage-probe.txt'
        probe.parent.mkdir(parents=True,exist_ok=True);probe.write_text('editorial-object-storage-v1\n',encoding='utf-8')
        status['stage']='cos_round_trip';store.upload(probe)
        digest=__import__('hashlib').sha256(probe.read_bytes()).hexdigest()
        result=store.cos().get_object(Bucket=os.environ['COS_BUCKET'],Key=f'editorial/{store.namespace}/sha256/{digest}')
        if result['Body'].get_raw_stream().read()!=probe.read_bytes():raise RuntimeError('COS round trip mismatch')
        status['cos']=True
        status['stage']='configure'
        subprocess.run([sys.executable,str(ROOT/'scripts/configure.py')],check=True,stdout=subprocess.DEVNULL)
        home=Path(os.environ['CODEX_HOME'])
        if os.environ.get('EDITORIAL_MODEL_API_KEY'):
            (home/'config.toml').write_text(provider_toml(os.environ['EDITORIAL_MODEL_BASE_URL'],os.environ['CODEX_MODEL']),encoding='utf-8')
            (home/'config.toml').chmod(0o600)
        session_folder=ROOT/'cloud/sessions';session_folder.mkdir(parents=True,exist_ok=True)
        if not (home/'sessions').exists():(home/'sessions').symlink_to(session_folder,target_is_directory=True)
        restored_auth=store.secret('codex_auth')
        if restored_auth:
            (home/'auth.json').write_bytes(restored_auth);(home/'auth.json').chmod(0o600)
            model=store.secret('codex_account_model')
            if model:
                os.environ['CODEX_MODEL']=validate_model(model.decode())
                (home/'config.toml').write_text('model = '+json.dumps(os.environ['CODEX_MODEL'])+'\n',encoding='utf-8')
                (home/'config.toml').chmod(0o600)
        desktop.start(store)
        # Credentials are never bundled; explicit account import uses the private admin API.
        if os.environ.get('OPENAI_API_KEY'):
            result=subprocess.run(['codex','login','--with-api-key'],input=os.environ['OPENAI_API_KEY'],
                text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            if result.returncode:raise RuntimeError('Codex API login failed')
        args=['node',str(bot/'bridge.mjs')]
        binding_path=bot/'state/binding.json'
        binding=json.loads(binding_path.read_text()) if binding_path.exists() else {}
        if not binding.get('chatid'):args.append('--bind')
        # Logs may include user content or auth errors: keep them off public build logs.
        log=Path('/tmp/editorial-bot.log').open('ab')
        child=subprocess.Popen(args,cwd=ROOT,env=os.environ,stdout=log,stderr=log)
        status['stage']='bot'
        status['phase']='waiting_for_group_binding' if '--bind' in args else 'running'
        while child.poll() is None:
            time.sleep(15);store.fence()
            # OAuth refresh updates are retained encrypted; session/content checkpoints
            # run at turn completion and before each manifest/outbox transition.
            auth=home/'auth.json'
            if auth.exists():store.secret('codex_auth',auth.read_bytes())
        status['phase']='bot_stopped';status['bot_exit_code']=child.returncode
    except Exception as error:
        status['phase']='failed';status['error_type']=type(error).__name__
        # MySQL errno helps distinguish auth/network failures without exposing address/password.
        if getattr(error,'args',None) and isinstance(error.args[0],int):status['error_code']=error.args[0]
        if hasattr(error,'get_error_code'):status['error_code']=error.get_error_code()
        if hasattr(error,'code') and isinstance(error.code,int):status['http_error_code']=error.code
        if child and child.poll() is None:child.kill()


def stop(*_):
    status['phase']='stopping'
    if child and child.poll() is None:
        child.terminate()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
    # Interrupted tasks stay running/replying; normal recovery marks outcome_unknown.
    if store:
        try:store.checkpoint()
        except Exception:pass
    desktop.stop()
    os._exit(0)


def main():
    for directory in ('jobs','outbox','state'):(studio/directory).mkdir(parents=True,exist_ok=True)
    (bot/'state').mkdir(parents=True,exist_ok=True)
    Path(os.environ['CODEX_HOME']).mkdir(parents=True,exist_ok=True)
    threading.Thread(target=ThreadingHTTPServer(('127.0.0.1',8790),Durability).serve_forever,daemon=True).start()
    spec=importlib.util.spec_from_file_location('workbench',ROOT/'editorial/workbench/server.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    proxy=desktop.frontend()
    # The authenticated management/status UI remains available if the optional
    # desktop proxy fails. Never fall back to an unauthenticated public server.
    server=module.Server(8788 if proxy else int(os.environ.get('PORT',8080)),
        module.Workbench(studio,bot,ROOT/'editorial/workbench/state'),host='127.0.0.1' if proxy else '0.0.0.0')
    server.cloud_status=cloud_status
    server.cloud_login=cloud_login
    server.cloud_import_auth=import_account_auth
    server.cloud_check_auth=check_account_auth
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    threading.Thread(target=start_worker,daemon=True).start()
    server.serve_forever()


if __name__=='__main__':main()
