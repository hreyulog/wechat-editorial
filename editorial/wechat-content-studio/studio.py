"""Durable, versioned content production and review delivery CLI."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
from settings import load_config
CONFIG = load_config()
for directory in ('jobs', 'outbox', 'state'):
    (ROOT / directory).mkdir(exist_ok=True)


def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path, data):
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def get_job(job_id):
    if not re.fullmatch(r'C\d{4,}', job_id): raise ValueError('Invalid job ID')
    return read(ROOT / 'jobs' / job_id / 'job.json')


def version_dir(job, version=None):
    number = int(version or job['version'])
    if number < 1: raise ValueError('Invalid version')
    return ROOT / 'jobs' / job['id'] / f'v{number}'


def new_job(kind, topic):
    # Exclusive directory creation also protects against two simultaneous create calls.
    for number in range(1, 100000):
        job_id = f'C{number:04}'
        folder = ROOT / 'jobs' / job_id
        try: folder.mkdir()
        except FileExistsError: continue
        break
    job = {'id': job_id, 'kind': kind, 'topic': topic, 'version': 1,
           'status': 'producing', 'created_at': now(), 'updated_at': now(), 'publish_enabled': False}
    folder.joinpath('v1/src').mkdir(parents=True)
    write(folder / 'job.json', job)
    write(folder / 'v1/brief.json', {'topic': topic, 'kind': kind, 'delivery_group': CONFIG['group']})
    return job


def set_status(job, status):
    job['status'], job['updated_at'] = status, now()
    write(ROOT / 'jobs' / job['id'] / 'job.json', job)


def revise(job_id, note):
    job = get_job(job_id)
    previous = version_dir(job)
    job['version'] += 1
    folder = version_dir(job)
    folder.joinpath('src').mkdir(parents=True)
    for name in ('article.json', 'brief.json', 'script.md', 'storyboard.md', 'sources.md'):
        if (previous / name).is_file(): shutil.copy2(previous / name, folder / name)
    if (previous / 'src').is_dir(): shutil.copytree(previous / 'src', folder / 'src', dirs_exist_ok=True)
    write(folder / 'revision.json', {'from_version': job['version'] - 1, 'note': note, 'at': now()})
    set_status(job, 'producing')
    return job


def checked_manifest(job, version=None):
    folder = version_dir(job, version)
    manifest = read(folder / 'manifest.json')
    for name, digest in {**manifest['sources'], **manifest['outputs']}.items():
        candidate = (folder / name).resolve()
        candidate.relative_to(folder.resolve())
        if sha(candidate) != digest: raise ValueError(f'Version changed after build: {name}; rebuild or revise')
    return folder, manifest


def build(job_id, version=None):
    job = get_job(job_id)
    folder = version_dir(job, version)
    if (folder / 'review.json').exists(): raise ValueError('Reviewed version is immutable; create a revision')
    if any(read(p).get('version') == int(folder.name[1:]) and read(p).get('job_id') == job_id
           for p in (ROOT / 'outbox').glob('*.json')):
        raise ValueError('Delivered/queued version is immutable; create a revision')
    command = [CONFIG['node'], str(ROOT / 'render.mjs'), str(folder), job['kind']]
    subprocess.run(command, check=True, cwd=ROOT)
    outputs = {}
    for name in ('article.html', 'wechat.html', 'article.md', 'article-preview.png', 'cover.png', 'review.mp4'):
        if (folder / name).is_file(): outputs[name] = sha(folder / name)
    sources = {}
    for path in [folder / 'article.json', *sorted((folder / 'src').rglob('*'))]:
        if path.is_file(): sources[str(path.relative_to(folder))] = sha(path)
    manifest = {'job_id': job_id, 'version': int(folder.name[1:]), 'built_at': now(),
                'sources': sources, 'outputs': outputs, 'qa': read(folder / 'qa.json')}
    write(folder / 'manifest.json', manifest)
    set_status(job, 'awaiting_review' if job['kind'] == 'video' else 'awaiting_official_preview')
    return manifest


def official_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'mp.weixin.qq.com' or parsed.username or parsed.port:
        raise ValueError('An official HTTPS mp.weixin.qq.com preview URL is required')
    if parsed.path not in ('/s', '/s/') and not parsed.path.startswith('/s/'):
        raise ValueError('Editor/admin URLs cannot be sent as article previews')
    return url


def attach_link(job_id, version, url, source_message_id):
    job = get_job(job_id)
    folder, _ = checked_manifest(job, version)
    if not source_message_id: raise ValueError('A real incoming WeChat message receipt is required')
    write(folder / 'official-preview.json', {'url': official_url(url), 'provenance': 'user_supplied_wechat_message',
                                           'source_message_id': source_message_id, 'attached_at': now()})
    return deliver(job_id, version)


def deliver(job_id, version=None):
    job = get_job(job_id)
    folder, manifest = checked_manifest(job, version)
    for area in (('article', 'video') if job['kind'] == 'both' else (job['kind'],)):
        if manifest.get('qa', {}).get(area, {}).get('passed') is not True:
            raise ValueError(f'{area} validation has not passed')
    visual = read(folder / 'visual-review.json')
    if visual.get('checked') is not True or not visual.get('notes'): raise ValueError('Actual visual review is required')
    number = int(folder.name[1:])
    # Local TurboPush storage is independent of browser publishing and group delivery.
    local_import = ROOT/'turbopush_local.py'
    if CONFIG.get('turbopush_enabled') and 'review.mp4' in manifest['outputs'] and local_import.is_file() and (Path.home()/'.TurboPush/mcp.json').is_file():
        result = subprocess.run([CONFIG['article_python'], '-X', 'utf8', str(local_import), job_id, '--version', str(number)],
                                cwd=ROOT, capture_output=True, encoding='utf-8')
        (folder/'turbopush-import.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode: print('TurboPush local import needs attention; see this version\'s turbopush-import.log',file=sys.stderr)
    parts = []
    files = []
    if 'review.mp4' in manifest['outputs']:
        files.append({'path': str(folder / 'review.mp4'), 'sha256': manifest['outputs']['review.mp4']})
        parts.append('视频审片：MP4文件随本任务送审。')
    official = folder / 'official-preview.json'
    if job['kind'] != 'video' and official.exists():
        parts.append('公众号草稿预览：' + official_url(read(official)['url']))
    elif job['kind'] != 'video':
        set_status(job, 'awaiting_official_preview')
        if not files: return {'job_id': job_id, 'status': job['status'], 'queued': False,
                              'blocker': 'Official WeChat draft preview link is not available'}
    text = f'{job_id}-v{number}｜{job["topic"]}\n' + '\n'.join(parts)
    destination = CONFIG.get('review_destination', {'provider': 'desktop_wechat', 'group': CONFIG['group']})
    text += f'\n审核意见请 @ 机器人：修改 {job_id} …；通过 {job_id}-v{number}。'
    signature = hashlib.sha256(json.dumps({'text': text, 'files': files, 'destination': destination}, sort_keys=True).encode()).hexdigest()[:16]
    path = ROOT / 'outbox' / f'{job_id}-v{number}-{signature}.json'
    if not path.exists():
        # A later real article link should not cause a previously queued/sent video to be repeated.
        prior_files = {f['sha256'] for p in (ROOT / 'outbox').glob(f'{job_id}-v{number}-*.json')
                       for prior in [read(p)] if prior.get('destination', {'provider': 'desktop_wechat', 'group': prior.get('group')}) == destination
                       and prior.get('status') not in ('failed', 'cancelled') for f in prior.get('files', [])}
        files = [f for f in files if f['sha256'] not in prior_files]
        write(path, {'job_id': job_id, 'version': number, 'group': CONFIG['group'], 'text': text,
                     'destination': destination, 'source_message_id': read(ROOT/'state/active-wecom-task.json').get('msgid') if (ROOT/'state/active-wecom-task.json').exists() else None, 'files': files, 'status': 'queued', 'created_at': now(), 'steps': []})
    if job['kind'] == 'video' or official.exists(): set_status(job, 'awaiting_review')
    return {'job_id': job_id, 'version': number, 'status': job['status'], 'outbox': str(path), 'delivery': read(path)['status']}


def official_step(job_id, step, version=None):
    command = [CONFIG['article_python'], '-X', 'utf8', str(ROOT/'official_drafts.py'), step, job_id]
    if version is not None: command += ['--version', str(version)]
    subprocess.run(command, cwd=ROOT, check=True)
    return {'job_id': job_id, 'step': step, 'completed': True}


def review(job_id, version, source_message_id):
    job = get_job(job_id)
    folder, manifest = checked_manifest(job, version)
    if not source_message_id: raise ValueError('User message receipt required')
    if job['kind'] != 'video' and not (folder / 'official-preview.json').exists():
        raise ValueError('Article has no official preview; it cannot be marked fully approved')
    write(folder / 'review.json', {'status': 'approved', 'source_message_id': source_message_id,
                                 'at': now(), 'manifest_sha256': sha(folder / 'manifest.json'), 'published': False})
    if int(version) == job['version']: set_status(job, 'approved')
    return {'job_id': job_id, 'version': int(version), 'status': 'approved', 'published': False}


def status(job_id=None):
    jobs = [get_job(job_id)] if job_id else [read(p) for p in sorted((ROOT / 'jobs').glob('*/job.json'))]
    for job in jobs:
        job['deliveries'] = [{'version': d['version'], 'status': d['status'], 'error': d.get('error')}
                             for p in (ROOT / 'outbox').glob(f'{job["id"]}-*.json') for d in [read(p)]]
    return jobs


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('new'); p.add_argument('--kind', choices=['article', 'video', 'both'], required=True); p.add_argument('--topic', required=True)
    p = sub.add_parser('revise'); p.add_argument('id'); p.add_argument('--note', required=True)
    for action in ('build', 'deliver'):
        p = sub.add_parser(action); p.add_argument('id'); p.add_argument('--version', type=int)
    p = sub.add_parser('status'); p.add_argument('id', nargs='?')
    p = sub.add_parser('official'); p.add_argument('id'); p.add_argument('--step',choices=['prepare','submit'],required=True); p.add_argument('--version',type=int)
    args = parser.parse_args()
    if args.action == 'new': result = new_job(args.kind, args.topic)
    elif args.action == 'revise': result = revise(args.id, args.note)
    elif args.action == 'build': result = build(args.id, args.version)
    elif args.action == 'deliver': result = deliver(args.id, args.version)
    elif args.action == 'official': result = official_step(args.id,args.step,args.version)
    else: result = status(args.id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
