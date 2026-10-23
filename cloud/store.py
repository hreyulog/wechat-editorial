"""MySQL documents/lease and private content-addressed COS objects.

Container disk is a mirror. JSON transitions commit to SQL before acknowledgement;
media is uploaded before a manifest/outbox transition is committed. A connection
scoped MySQL advisory lock serializes rolling versions of this Bot installation.
"""
import hashlib
import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ('editorial/wechat-content-studio/jobs/', 'editorial/wechat-content-studio/outbox/',
            'editorial/wechat-content-studio/state/', 'editorial/wecom-bot-local/state/',
            'editorial/workbench/state/', 'cloud/sessions/')
EXCLUDED = {'listener.lock', 'connectivity.json', 'upload-progress.json'}
CONFIG_PATH = 'editorial/wechat-content-studio/config.json'


def safe_path(value, root=ROOT):
    path = Path(value)
    if not path.is_absolute():
        path = root/path
    key = path.resolve().relative_to(root.resolve()).as_posix()
    if (key != CONFIG_PATH and not key.startswith(PREFIXES)) or path.name in EXCLUDED or path.suffix in ('.tmp', '.lock'):
        raise ValueError('Path is outside durable content roots')
    return path, key


class Store:
    def __init__(self):
        import pymysql
        self.mysql = pymysql
        self.namespace = hashlib.sha256(os.environ['WECOM_BOT_ID'].encode()).hexdigest()[:32]
        address = os.environ['MYSQL_ADDRESS'].rsplit(':', 1)
        self.options = dict(host=address[0], port=int(address[1]) if len(address)>1 else 3306,
            user=os.environ['MYSQL_USERNAME'], password=os.environ['MYSQL_PASSWORD'],
            charset='utf8mb4', connect_timeout=15, read_timeout=30, write_timeout=30, autocommit=True)
        self.database = os.environ.get('EDITORIAL_DATABASE', 'wechat_editorial')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,50}', self.database):
            raise ValueError('Invalid database name')
        self.guard = threading.RLock()
        self.lease = None
        self.credentials = None

    def connect(self):
        return self.mysql.connect(**self.options, database=self.database)

    def acquire(self):
        with self.mysql.connect(**self.options) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{self.database}` CHARACTER SET utf8mb4')
        connection = self.connect()
        with connection.cursor() as cursor:
            cursor.execute('SELECT GET_LOCK(%s, 1)', ('editorial:'+self.namespace,))
            if cursor.fetchone()[0] != 1:
                connection.close()
                return False
            cursor.execute('''CREATE TABLE IF NOT EXISTS editorial_files (
                namespace CHAR(32) NOT NULL, path_hash CHAR(64) NOT NULL, path TEXT NOT NULL,
                document MEDIUMTEXT NULL, object_key TEXT NULL, sha256 CHAR(64) NULL,
                size BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6)
                ON UPDATE CURRENT_TIMESTAMP(6), PRIMARY KEY(namespace,path_hash))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS editorial_secrets (
                namespace CHAR(32) NOT NULL, name VARCHAR(80) NOT NULL, ciphertext MEDIUMBLOB NOT NULL,
                PRIMARY KEY(namespace,name))''')
        self.lease = connection
        return True

    def fence(self):
        with self.guard:
            if self.lease is None:
                raise RuntimeError('Worker has no database lease')
            # Never reconnect an advisory-lock connection: reconnection loses ownership.
            with self.lease.cursor() as cursor:
                cursor.execute('SELECT IS_USED_LOCK(%s)=CONNECTION_ID()', ('editorial:'+self.namespace,))
                if cursor.fetchone()[0] != 1:
                    raise RuntimeError('Worker database lease lost')

    def cos(self):
        from qcloud_cos import CosConfig, CosS3Client
        if not self.credentials or self.credentials['expired_time'] < time.time()+300:
            query=urllib.parse.urlencode({'autodev':1,'appid':os.environ['WXCLOUD_APPID']})
            request=urllib.request.Request('https://servicewechat.com/wxa-dev-qbase/gettcbtoken?'+query,
                data=json.dumps({'region':os.environ['COS_REGION'],'source':os.environ['COS_BUCKET'],
                    'scene':'TOKEN_SCENE_COS','service':'cos'}).encode(), headers={
                    'Content-Type':'application/json','X-CloudRunCli-Robot':'1',
                    'X-CloudRunCli-Key':os.environ['WXCLOUD_CLI_KEY']})
            # Never follow a redirect carrying the CLI credential.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_args, **_kwargs):
                    raise RuntimeError('Credential request redirect refused')
            with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
                result=json.load(response)
            if result.get('base_resp',{}).get('ret') != 0:
                raise RuntimeError('COS credential refresh failed')
            self.credentials=result
        c=self.credentials
        return CosS3Client(CosConfig(Region=os.environ['COS_REGION'],SecretId=c['secretid'],
            SecretKey=c['secretkey'],Token=c['token'],Scheme='https'))

    def secret(self, name, value=None):
        """Only credentials created by an explicit cloud login; no desktop cache import."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        cipher=AESGCM(base64.b64decode(os.environ['EDITORIAL_MASTER_KEY']))
        associated=(self.namespace+':'+name).encode()
        self.fence()
        with self.connect() as connection, connection.cursor() as cursor:
            if value is not None:
                nonce=os.urandom(12);encrypted=nonce+cipher.encrypt(nonce,value,associated)
                cursor.execute('INSERT INTO editorial_secrets(namespace,name,ciphertext) VALUES(%s,%s,%s) '
                    'ON DUPLICATE KEY UPDATE ciphertext=VALUES(ciphertext)',(self.namespace,name,encrypted))
                return
            cursor.execute('SELECT ciphertext FROM editorial_secrets WHERE namespace=%s AND name=%s',(self.namespace,name))
            row=cursor.fetchone()
            return cipher.decrypt(row[0][:12],row[0][12:],associated) if row else None

    def upsert(self, key, document=None, object_key=None, digest=None, size=0):
        self.fence()
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('''INSERT INTO editorial_files(namespace,path_hash,path,document,object_key,sha256,size)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE document=VALUES(document),
                object_key=VALUES(object_key),sha256=VALUES(sha256),size=VALUES(size)''',
                (self.namespace,hashlib.sha256(key.encode()).hexdigest(),key,document,object_key,digest,size))

    def upload(self, path):
        path,key=safe_path(path)
        raw_hash=hashlib.sha256()
        with path.open('rb') as source:
            for part in iter(lambda:source.read(1024*1024),b''):raw_hash.update(part)
        digest=raw_hash.hexdigest()
        object_key=f'editorial/{self.namespace}/sha256/{digest}'
        size=path.stat().st_size
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT sha256 FROM editorial_files WHERE namespace=%s AND path_hash=%s',
                (self.namespace,hashlib.sha256(key.encode()).hexdigest()))
            row=cursor.fetchone()
            if row and row[0]==digest:return
        self.fence()
        client=self.cos()
        client.upload_file(Bucket=os.environ['COS_BUCKET'],Key=object_key,LocalFilePath=str(path),
            PartSize=8,MAXThread=2,EnableMD5=True)
        result=client.head_object(Bucket=os.environ['COS_BUCKET'],Key=object_key)
        if int(result['Content-Length'])!=size:
            raise RuntimeError('COS length verification failed')
        # Re-hash the working file: a concurrent render must not commit a mixed snapshot.
        verify=hashlib.sha256()
        with path.open('rb') as source:
            for part in iter(lambda:source.read(1024*1024),b''):verify.update(part)
        if verify.hexdigest()!=digest:raise RuntimeError('File changed during checkpoint')
        self.upsert(key,object_key=object_key,digest=digest,size=size)

    def write(self, path, data):
        # Lock remains held through COS checkpoint + SQL commit: no background snapshot
        # can overwrite a newer authoritative JSON transition with an older local copy.
        with self.guard:
            local=Path(path).resolve()
            if local.name in EXCLUDED:return False
            local,key=safe_path(local)
            if '/outbox/' in key and re.fullmatch(r'C\d{4,}',str(data.get('job_id',''))) and isinstance(data.get('version'),int):
                self.checkpoint(ROOT/'editorial/wechat-content-studio/jobs'/data['job_id']/f"v{data['version']}")
            elif local.name=='manifest.json':
                self.checkpoint(local.parent)
            text=json.dumps(data,ensure_ascii=False)
            self.upsert(key,document=text,size=len(text.encode()))
            local.parent.mkdir(parents=True,exist_ok=True)
            temp=local.with_name(local.name+'.'+uuid.uuid4().hex+'.tmp')
            temp.write_text(text,encoding='utf-8');os.replace(temp,local)
            return True

    def checkpoint(self, folder=None):
        with self.guard:
            folders=[folder] if folder else [ROOT/prefix for prefix in PREFIXES]
            count=0
            for source in folders:
                for path in sorted(source.rglob('*')):
                    if not path.is_file() or path.is_symlink() or path.name in EXCLUDED or path.suffix in ('.tmp','.lock'):
                        continue
                    # JSON from explicit wrappers is authoritative in SQL. Direct source
                    # JSON files still need a checkpoint before manifest/delivery.
                    _,key=safe_path(path)
                    if path.suffix=='.json':
                        data=json.loads(path.read_text(encoding='utf-8-sig'))
                        self.upsert(key,document=json.dumps(data,ensure_ascii=False))
                    else:self.upload(path)
                    count+=1
            return count

    def restore(self):
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT path,document,object_key,sha256,size FROM editorial_files WHERE namespace=%s', (self.namespace,))
            records=cursor.fetchall()
        client=None
        for key,document,object_key,digest,size in records:
            path,_=safe_path(key)
            path.parent.mkdir(parents=True,exist_ok=True)
            if document is not None:path.write_text(document,encoding='utf-8')
            else:
                if client is None:client=self.cos()
                client.download_file(Bucket=os.environ['COS_BUCKET'],Key=object_key,DestFilePath=str(path))
                checksum=hashlib.sha256()
                with path.open('rb') as source:
                    for part in iter(lambda:source.read(1024*1024),b''):checksum.update(part)
                if path.stat().st_size!=size or checksum.hexdigest()!=digest:
                    raise RuntimeError('Restored object failed SHA256 verification')
        return len(records)
