"""Local operations workbench. Reads production receipts; writes its own plans only."""
import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import threading
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
JOB = re.compile(r'C\d{4,}')
ASSETS = {'cover.png', 'article-preview.png', 'review.mp4', 'article.md', 'script.md', 'storyboard.md', 'sources.md'}
STATUS = {
    'producing': ('制作中', 'production'), 'awaiting_official_preview': ('待生成文章草稿', 'draft'),
    'awaiting_video_embed': ('待插入视频', 'attention'), 'awaiting_review': ('待审核', 'review'),
    'approved': ('文章审核已通过', 'review'),
    'video_draft_upload_authorized': ('已确认，待上传视频草稿', 'draft'),
    'video_draft_uploaded': ('视频草稿已上传', 'draft'),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def within(path, root):
    path.resolve().relative_to(root.resolve())
    return path.resolve()


def load(path, default=None):
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return default
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def official_preview(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == 'https' and parsed.netloc == 'mp.weixin.qq.com' and (parsed.path == '/s' or parsed.path.startswith('/s/')):
            return value
    except ValueError:
        pass
    return None


def age_seconds(value):
    try:
        return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(value.replace('Z', '+00:00'))).total_seconds())
    except (AttributeError, ValueError, TypeError):
        return None


class Workbench:
    def __init__(self, studio, bot, state):
        self.studio, self.bot, self.state = Path(studio).resolve(), Path(bot).resolve(), Path(state).resolve()
        self.lock = threading.Lock()

    def read(self, path, root=None, default=None):
        try:
            return load(within(path, root or self.studio), default)
        except ValueError:
            return default

    def version(self, job_id, number):
        if not JOB.fullmatch(job_id) or not isinstance(number, int) or not 0 < number < 100000:
            raise ValueError('内容编号或版本不合法')
        return within(self.studio/'jobs'/job_id/f'v{number}', self.studio)

    def plans(self):
        source = self.state/'plans.json'
        value = self.read(source, self.state) if source.exists() else {'revision': 0, 'items': []}
        if not isinstance(value, dict) or not isinstance(value.get('revision'), int) or not isinstance(value.get('items'), list) or any(
                not isinstance(item, dict) or not item.get('id') or not item.get('created_at') for item in value.get('items', [])):
            raise ValueError('选题排期数据损坏，请先恢复 plans.json')
        return value

    def save_plan(self, data):
        allowed = {'id', 'revision', 'topic', 'kind', 'channel', 'owner', 'date', 'notes', 'job_id', 'archived'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('选题字段不合法')
        lengths = {'topic': 200, 'owner': 80, 'notes': 4000, 'job_id': 30, 'date': 10}
        for key, limit in lengths.items():
            if not isinstance(data.get(key, ''), str) or len(data.get(key, '')) > limit:
                raise ValueError(f'{key} 字段不合法或过长')
        if not data.get('topic', '').strip():
            raise ValueError('请填写选题')
        if data.get('kind') not in ('article', 'video', 'both') or data.get('channel') not in ('wechat', 'channels', 'both'):
            raise ValueError('请选择内容类型与目标平台')
        if data.get('date'):
            date.fromisoformat(data['date'])
        if data.get('job_id'):
            if not JOB.fullmatch(data['job_id']) or not self.read(self.studio/'jobs'/data['job_id']/'job.json'):
                raise ValueError('关联的内容编号不存在')
        if not isinstance(data.get('archived', False), bool):
            raise ValueError('归档状态不合法')
        with self.lock:
            store = self.plans()
            if data.get('revision') != store['revision']:
                raise Conflict('排期已被更新，请刷新后再保存')
            previous = next((p for p in store['items'] if p['id'] == data.get('id')), None)
            if data.get('id') and previous is None:
                raise ValueError('选题不存在')
            plan = {key: data.get(key, '') for key in ('topic', 'kind', 'channel', 'owner', 'date', 'notes', 'job_id')}
            plan.update(id=previous['id'] if previous else 'P'+secrets.token_hex(4),
                        created_at=previous['created_at'] if previous else now(), updated_at=now(),
                        archived=data.get('archived', False))
            store['items'] = [p for p in store['items'] if p['id'] != plan['id']] + [plan]
            store['revision'] += 1
            self.state.mkdir(parents=True, exist_ok=True)
            temporary = self.state/('plans.'+secrets.token_hex(8)+'.tmp')
            temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding='utf-8')
            if os.environ.get('EDITORIAL_CLOUD'):
                import sys
                sys.path.insert(0, str(ROOT.parents[1]))
                from cloud.client import persist
                persist(self.state/'plans.json', store)
            os.replace(temporary, self.state/'plans.json')
            return store

    def version_summary(self, job_id, number):
        folder = self.version(job_id, number)
        article = self.read(folder/'article.json') or {}
        metadata = self.read(folder/'video-metadata.json') or {}
        qa = (self.read(folder/'manifest.json') or {}).get('qa', {})
        receipt = self.read(folder/'official/receipt.json') or {}
        preview = self.read(folder/'official-preview.json') or {}
        remote = self.read(folder/'turbopush-remote.json') or {}
        approval = self.read(folder/'video-draft-approval.json') or {}
        files = []
        for name in sorted(ASSETS):
            try:
                path = within(folder/name, folder)
                if path.is_file():
                    files.append({'name': name, 'bytes': path.stat().st_size,
                                  'url': f'/media/{job_id}/v{number}/{name}'})
            except ValueError:
                continue
        account = metadata.get('account', '')
        if isinstance(account, dict):
            account = account.get('name', '')
        video_qa = qa.get('video') if isinstance(qa.get('video'), dict) else {}
        article_qa = qa.get('article') if isinstance(qa.get('article'), dict) else {}
        return {'version': number, 'title': article.get('title') or metadata.get('title') or '',
                'video_title': metadata.get('title', ''), 'description': metadata.get('description', ''),
                'account': account, 'files': files,
                'official_preview': official_preview(preview.get('url')),
                'article_draft': receipt.get('state', 'not_created'),
                'video_component_preserved': receipt.get('video_component_check', {}).get('preserved'),
                'video_draft_confirmed': approval.get('action') == 'save_video_draft' and bool(approval.get('source_message_id')),
                'video_draft_uploaded': remote.get('record_success') is True and remote.get('syncDraft') is True,
                'upload_status': remote.get('status', 'not_uploaded'), 'record_id': remote.get('record_id'),
                'qa': {'article_passed': article_qa.get('passed'), 'video_passed': video_qa.get('passed'),
                       'duration_seconds': video_qa.get('duration_seconds'), 'width': video_qa.get('width'),
                       'height': video_qa.get('height'), 'full_decode': video_qa.get('full_decode')},
                'review_status': (self.read(folder/'review.json') or {}).get('status', 'pending')}

    def tasks(self):
        items, issues = [], []
        for path in sorted((self.studio/'jobs').glob('C*/job.json')):
            if not JOB.fullmatch(path.parent.name):
                continue
            try:
                job = self.read(path)
                if not isinstance(job, dict) or job.get('id') != path.parent.name:
                    raise ValueError()
                current = self.version_summary(job['id'], job['version'])
                status = str(job.get('status', 'unknown'))
                label, lane = STATUS.get(status, (status, 'attention'))
                items.append({'id': job['id'], 'topic': job.get('topic', ''), 'kind': job.get('kind'),
                              'status': status, 'status_label': label, 'lane': lane,
                              'created_at': job.get('created_at'), 'updated_at': job.get('updated_at'),
                              'current': current})
            except (ValueError, KeyError, TypeError, AttributeError):
                issues.append(path.parent.name)
        return sorted(items, key=lambda x: x['updated_at'] or '', reverse=True), issues

    def queue(self, directory, root):
        counts, failures = {}, []
        for path in directory.glob('*.json'):
            item = self.read(path, root)
            if not isinstance(item, dict):
                counts['unreadable'] = counts.get('unreadable', 0) + 1
                continue
            status = str(item.get('status', 'unknown'))
            counts[status] = counts.get(status, 0) + 1
            if status in ('outcome_unknown', 'delivery_unknown', 'upload_failed', 'failed', 'control_unknown'):
                failures.append({'job_id': item.get('job_id'), 'version': item.get('version'),
                                 'status': status, 'at': item.get('failed_at') or item.get('received_at') or item.get('created_at')})
        return {'counts': counts, 'attention': failures[-12:]}

    def integrations(self):
        connectivity = self.read(self.bot/'state/connectivity.json', self.bot) or {}
        heartbeat = connectivity.get('last_health_at') or connectivity.get('updated_at')
        age = age_seconds(heartbeat)
        online = connectivity.get('authenticated') is True and connectivity.get('socket_connected') is True
        production = self.read(self.bot/'state/production.json', self.bot) or {}
        official = self.read(self.studio/'state/official-api-check.json') or {}
        turbo = self.read(self.studio/'state/turbopush-mcp.json') or {}
        turbo_check = self.read(self.bot/'state/turbopush-mcp-check.json', self.bot) or {}
        return [
            {'id':'wecom', 'name':'企业微信', 'status':'online' if online and age is not None and age < 45 else 'stale' if online else 'unknown',
             'label':'连接正常' if online and age is not None and age < 45 else '心跳已过期' if online else '未确认在线',
             'checked_at':heartbeat, 'detail':'任务入口与原会话送审'},
            {'id':'codex', 'name':'内容执行器', 'status':'busy' if production.get('phase') == 'processing' and online and age is not None and age < 45 else 'unknown',
             'label':'制作中' if production.get('phase') == 'processing' and online and age is not None and age < 45 else '等待任务' if online and age is not None and age < 45 else '待确认',
             'checked_at':production.get('updated_at'), 'detail':'原生会话 · 最长 4 小时'},
            {'id':'official', 'name':'微信公众号', 'status':'recorded' if official.get('draft_count_readable') else 'unknown',
             'label':'有草稿接口检查记录' if official.get('draft_count_readable') else '尚无检查记录',
             'checked_at':official.get('checked_at'), 'detail':'草稿预览与视频卡片读回'},
            {'id':'turbopush', 'name':'TurboPush / 视频号', 'status':'configured' if turbo.get('enabled') else 'unknown',
             'label':'已配置 MCP，在线待确认' if turbo.get('enabled') else '未检测到 MCP 配置',
             'checked_at':turbo_check.get('checked_at'), 'detail':'审片确认后保存视频号草稿'},
        ]

    def snapshot(self):
        tasks, issues = self.tasks()
        incoming = self.queue(self.bot/'state/inbox', self.bot)
        outgoing = self.queue(self.studio/'outbox', self.studio)
        plans = self.plans()
        return {'name':'自媒体运营管理工作台', 'generated_at':now(), 'tasks':tasks, 'plans':plans,
                'integrations':self.integrations(), 'queues':{'incoming':incoming, 'outgoing':outgoing},
                'data_issues':issues, 'studio_exists':self.studio.is_dir(),
                'stats':{'total':len(tasks), 'producing':sum(t['lane']=='production' for t in tasks),
                         'review':sum(t['status']=='awaiting_review' for t in tasks),
                         'drafts':sum(bool(t['current']['official_preview']) or t['current']['video_draft_uploaded'] for t in tasks),
                         'attention':len(issues)+sum(t['lane']=='attention' for t in tasks)+len(incoming['attention'])+len(outgoing['attention'])}}

    def detail(self, job_id):
        job = self.read(self.studio/'jobs'/job_id/'job.json') if JOB.fullmatch(job_id) else None
        if not job or job.get('id') != job_id:
            raise FileNotFoundError()
        versions = []
        for path in (self.studio/'jobs'/job_id).glob('v*'):
            if re.fullmatch(r'v[1-9]\d*', path.name) and path.is_dir():
                versions.append(self.version_summary(job_id, int(path.name[1:])))
        folder = self.version(job_id, job['version'])
        article = self.read(folder/'article.json') or {}
        return {'id':job_id, 'topic':job.get('topic'), 'kind':job.get('kind'), 'current_version':job['version'],
                'versions':sorted(versions, key=lambda v:v['version'], reverse=True),
                'article':{'title':article.get('title', ''), 'subtitle':article.get('subtitle', ''),
                           'sections':article.get('sections', []), 'sources':article.get('sources', [])}}


class Conflict(ValueError):
    pass


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, workbench, host='127.0.0.1'):
        self.workbench, self.session = workbench, secrets.token_urlsafe(32)
        self.cloud_origin = os.environ.get('EDITORIAL_PUBLIC_ORIGIN') if os.environ.get('EDITORIAL_CLOUD') else None
        super().__init__((host, port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'EditorialWorkbench/1.0'

    def log_message(self, *_):
        pass  # Do not log draft preview queries, credentials, or user content.

    def check_origin(self):
        if self.server.cloud_origin:
            expected = urlsplit(self.server.cloud_origin)
            if self.headers.get('Host') != expected.netloc or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise PermissionError()
            if self.headers.get('Origin') not in (None, self.server.cloud_origin):
                raise PermissionError()
            return
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError()
        if self.headers.get('Origin') not in (None, *('http://'+host for host in hosts)):
            raise PermissionError()

    def authorized(self):
        if self.server.cloud_origin:
            try:
                value = base64.b64decode(self.headers.get('Authorization','').removeprefix('Basic '), validate=True).decode()
                if secrets.compare_digest(value, 'admin:'+os.environ['EDITORIAL_ADMIN_PASSWORD']):
                    return True
            except (ValueError, UnicodeError):
                pass
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            value = cookie.get('editorial_session')
            return bool(value and secrets.compare_digest(value.value, self.server.session))
        except ValueError:
            return False

    def send_headers(self, status, content_type, length=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if length is not None:
            self.send_header('Content-Length', str(length))

    def json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_headers(status, 'application/json; charset=utf-8', len(raw))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if self.server.cloud_origin and self.path == '/healthz':
                return self.json(200, {'alive':True})
            self.check_origin()
            if self.server.cloud_origin and not self.authorized():
                self.send_headers(401, 'text/plain; charset=utf-8', 0)
                self.send_header('WWW-Authenticate', 'Basic realm="Editorial", charset="UTF-8"')
                self.end_headers()
                return
            path = unquote(urlsplit(self.path).path)
            if self.server.cloud_origin and path == '/api/cloud/status':
                return self.json(200, self.server.cloud_status())
            static = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}
            if path in static:
                raw = (ROOT/'web'/static[path]).read_bytes()
                self.send_headers(200, {'/':'text/html', '/app.js':'text/javascript', '/style.css':'text/css'}[path]+'; charset=utf-8', len(raw))
                if path == '/':
                    secure = '; Secure' if self.server.cloud_origin else ''
                    self.send_header('Set-Cookie', f'editorial_session={self.server.session}; HttpOnly; SameSite=Strict; Path=/{secure}')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(raw)
                return
            if not self.authorized():
                raise PermissionError()
            if path == '/api/snapshot':
                value = self.server.workbench.snapshot()
                if self.server.cloud_origin:
                    value['cloud'] = self.server.cloud_status()
                return self.json(200, value)
            match = re.fullmatch(r'/api/tasks/(C\d{4,})', path)
            if match:
                return self.json(200, self.server.workbench.detail(match[1]))
            match = re.fullmatch(r'/media/(C\d{4,})/v([1-9]\d*)/([^/]+)', path)
            if match and match[3] in ASSETS:
                folder = self.server.workbench.version(match[1], int(match[2]))
                return self.media(within(folder/match[3], folder))
            self.json(404, {'error':'页面不存在'})
        except PermissionError:
            self.json(403, {'error':'请从本机工作台打开'})
        except (FileNotFoundError, ValueError):
            self.json(404, {'error':'内容不存在或数据暂不可读'})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def media(self, path):
        total = path.stat().st_size
        start, end, status = 0, total-1, HTTPStatus.OK
        value = self.headers.get('Range')
        if value:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
            try:
                if not match or not any(match.groups()) or total == 0:
                    raise ValueError()
                if not match[1]:
                    suffix = int(match[2])
                    if suffix < 1:
                        raise ValueError()
                    start = max(0, total-suffix)
                else:
                    start = int(match[1]); end = min(int(match[2]), total-1) if match[2] else end
                if start > end or start >= total:
                    raise ValueError()
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_headers(416, 'text/plain', 0)
                self.send_header('Content-Range', f'bytes */{total}'); self.end_headers(); return
        self.send_headers(status, mimetypes.guess_type(path.name)[0] or 'text/plain; charset=utf-8', max(0, end-start+1))
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{total}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with path.open('rb') as source:
            source.seek(start)
            remaining = end-start+1
            while remaining > 0:
                chunk = source.read(min(256*1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk); remaining -= len(chunk)

    def do_POST(self):
        try:
            self.check_origin()
            if not self.authorized() or not self.headers.get('Origin'):
                raise PermissionError()
            if self.server.cloud_origin and self.path == '/api/cloud/auth/device':
                return self.json(200, self.server.cloud_login())
            if self.path != '/api/plans' or self.headers.get_content_type() != 'application/json':
                return self.json(404, {'error':'操作不存在'})
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 24000:
                return self.json(413, {'error':'请求过大或为空'})
            data = json.loads(self.rfile.read(length))
            result = self.server.workbench.save_plan(data)
            self.json(200, result)
        except PermissionError:
            self.json(403, {'error':'请求来源不匹配'})
        except Conflict as error:
            self.json(409, {'error':str(error)})
        except (ValueError, TypeError) as error:
            self.json(400, {'error':str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--studio', type=Path, default=ROOT.parent/'wechat-content-studio')
    parser.add_argument('--bot', type=Path, default=ROOT.parent/'wecom-bot-local')
    parser.add_argument('--state-dir', type=Path, default=ROOT/'state')
    parser.add_argument('--port', type=int, default=8788)
    args = parser.parse_args()
    server = Server(args.port, Workbench(args.studio, args.bot, args.state_dir))
    print(f'自媒体运营管理工作台：http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
