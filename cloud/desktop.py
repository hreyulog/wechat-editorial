"""Private Linux desktop behind the same authenticated HTTPS workbench origin."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from cloud.store import ROOT

processes=[]
turbo_status={'installed':False,'backend_ready':False,'account_login_verified':False}


def frontend():
    try:
        password=subprocess.run(['openssl','passwd','-6','-stdin'],input=os.environ['EDITORIAL_ADMIN_PASSWORD']+'\n',
            text=True,capture_output=True,check=True).stdout.strip()
        auth=Path('/tmp/editorial.htpasswd');auth.write_text('admin:'+password+'\n');auth.chmod(0o600)
        log=Path('/tmp/editorial-nginx.log').open('ab')
        process=subprocess.Popen(['nginx','-c',str(ROOT/'cloud/nginx.conf'),'-g','daemon off;'],
            stdout=subprocess.DEVNULL,stderr=log)
        processes.append(process);time.sleep(.3)
        turbo_status['frontend_ready']=process.poll() is None
        if process.poll() is not None:turbo_status['frontend_exit_code']=process.returncode
        return process.poll() is None
    except Exception as error:
        turbo_status['frontend_ready']=False;turbo_status['frontend_error_type']=type(error).__name__
        return False


def start(store):
    home=Path('/runtime/turbopush');data=home/'.TurboPush';data.mkdir(parents=True,exist_ok=True)
    os.environ['HOME']=str(home)
    os.environ['DISPLAY']=':99'
    environment={**os.environ,'HOME':str(home),'WEBKIT_DISABLE_DMABUF_RENDERER':'1'}
    saved=store.secret('turbopush_database')
    if saved:(data/'data.db').write_bytes(saved)
    processes.append(subprocess.Popen(['Xvfb',':99','-screen','0','1366x768x24','-nolisten','tcp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    time.sleep(1)
    processes.append(subprocess.Popen(['openbox'],env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    processes.append(subprocess.Popen(['x11vnc','-display',':99','-localhost','-rfbport','5900','-nopw','-forever','-shared'],
        env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    processes.append(subprocess.Popen(['websockify','127.0.0.1:6080','127.0.0.1:5900'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    # The native app owns its Go backend and creates ~/.TurboPush/mcp.json itself.
    log=Path('/tmp/editorial-turbopush.log').open('ab')
    native=subprocess.Popen(['dbus-run-session','--','/opt/turbopush/turbopush'],
        env=environment,cwd='/tmp',stdout=log,stderr=log)
    processes.append(native)
    turbo_status['installed']=True
    def monitor():
        last=None
        while True:
            time.sleep(15)
            try:
                store.fence()
                turbo_status['native_exit_code']=native.poll()
                config=data/'mcp.json'
                if config.exists():
                    value=json.loads(config.read_text())
                    if value.get('port') and value.get('auth'):
                        os.environ['TURBO_PUSH_PORT']=str(value['port']);os.environ['TURBO_PUSH_AUTH']=value['auth']
                        # Credentials stay in the native app's home, not this public config.
                        binary=Path('/opt/turbopush/turbo-push-mcp')
                        store.write(ROOT/'editorial/wechat-content-studio/state/turbopush-mcp.json',{
                            'enabled':True,'command':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                            'scope':'full-mcp-surface','enabled_tool_count':21,
                            'credentials_source':'Cloud TurboPush native home; no desktop credentials imported'})
                        turbo_status['backend_ready']=True
                        try:
                            request=urllib.request.Request('http://127.0.0.1:'+str(value['port'])+'/account/logged?simple=true',
                                headers={'Authorization':value['auth']})
                            with urllib.request.urlopen(request,timeout=5) as response:accounts=json.load(response)
                            turbo_status['account_login_verified']=accounts.get('code')==200
                            turbo_status['account_count']=len(accounts.get('data') or []) if isinstance(accounts.get('data'),list) else None
                        except urllib.error.HTTPError as error:
                            turbo_status['account_login_verified']=False;turbo_status['account_check_http_status']=error.code
                source=data/'data.db'
                if source.exists() and source.stat().st_mtime_ns!=last:
                    with tempfile.TemporaryDirectory() as temporary:
                        backup=Path(temporary)/'data.db'
                        with sqlite3.connect(source) as connection,sqlite3.connect(backup) as destination:
                            connection.backup(destination)
                        store.secret('turbopush_database',backup.read_bytes())
                    last=source.stat().st_mtime_ns
            except Exception as error:
                turbo_status['last_error_type']=type(error).__name__
    threading.Thread(target=monitor,daemon=True).start()


def stop():
    for process in reversed(processes):
        if process.poll() is None:process.terminate()
