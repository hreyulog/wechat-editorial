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


def checked_phone_preview(job, version=None):
    folder, manifest = checked_manifest(job, version)
    preview = read(folder / 'phone-preview.json')
    if preview.get('provenance') != 'video_channel_phone_preview':
        raise ValueError('A real video-channel phone preview is required')
    if preview.get('manifest_sha256') != sha(folder / 'manifest.json') or preview.get('video_sha256') != manifest['outputs'].get('review.mp4'):
        raise ValueError('Phone preview belongs to a different video build')
    if not preview.get('account') or not preview.get('remote_record_id'):
        raise ValueError('Phone preview must identify its target account and remote draft')
    binding = preview.get('draft_receipt', {})
    if not isinstance(binding, dict) or not binding.get('path'): raise ValueError('A verified video-channel draft receipt is required')
    draft_path = (folder / binding['path']).resolve()
    draft_path.relative_to(folder.resolve())
    if sha(draft_path) != binding.get('sha256'): raise ValueError('Video draft receipt changed')
    draft = read(draft_path)
    if draft.get('syncDraft') is not True or draft.get('published') is not False or draft.get('public_publish_attempted') is not False or draft.get('record_success') is not True or draft.get('record_status') != 4 or not draft.get('record_id'):
        raise ValueError('Draft upload must have a successful read-back record without public publication')
    if draft.get('job_id') != job['id'] or int(draft.get('version', 0)) != int(folder.name[1:]) or draft.get('video_sha256') != preview['video_sha256']:
        raise ValueError('Draft upload belongs to a different video version')
    account = preview['account']
    account_id = account.get('id') if isinstance(account, dict) else None
    if (account_id is not None and str(account_id) != str(draft.get('account_id'))) or (account_id is None and account not in (draft.get('account_name'), draft.get('account_id'))):
        raise ValueError('Draft upload belongs to a different account')
    if 'turbo_push.get_record_info' not in draft.get('verified_via', []): raise ValueError('Draft upload needs actual record read-back verification')
    url = preview.get('url')
    if url:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not (parsed.hostname == 'weixin.qq.com' or (parsed.hostname or '').endswith('.weixin.qq.com')) or parsed.username or parsed.port:
            raise ValueError('Phone preview must use a real official HTTPS WeChat URL')
        if parsed.path.startswith('/cgi-bin/') or parsed.path.rstrip('/') in ('', '/platform', '/platform/post', '/platform/post/create'):
            raise ValueError('An account home or editor URL is not a phone preview')
    image = preview.get('image')
    if image:
        candidate = (folder / image['path']).resolve()
        candidate.relative_to((folder / 'src').resolve())
        if sha(candidate) != image['sha256']: raise ValueError('Phone preview QR image changed')
    if not url and not image: raise ValueError('Phone preview has no link or QR image')
    if preview.get('expires_at'):
        expires = datetime.fromisoformat(preview['expires_at'].replace('Z', '+00:00'))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc): raise ValueError('Phone preview expired; obtain and send a fresh preview')
    return folder, preview


def attach_phone_preview(job_id, version, receipt):
    job = get_job(job_id)
    folder, manifest = checked_manifest(job, version)
    if 'review.mp4' not in manifest['outputs']: raise ValueError('This version has no video')
    source = Path(receipt).resolve()
    source.relative_to(folder.resolve())
    preview = read(source)
    if preview.get('video_sha256') != manifest['outputs']['review.mp4']: raise ValueError('Preview source must identify the exact video hash')
    draft_path = (folder / preview.get('draft_receipt', '')).resolve()
    draft_path.relative_to(folder.resolve())
    if not draft_path.is_file(): raise ValueError('A real draft upload receipt is required')
    preview['draft_receipt'] = {'path': str(draft_path.relative_to(folder)), 'sha256': sha(draft_path)}
    preview.update(manifest_sha256=sha(folder / 'manifest.json'), video_sha256=manifest['outputs']['review.mp4'])
    if preview.get('qr_image'):
        image = (folder / preview.pop('qr_image')).resolve()
        image.relative_to((folder / 'src').resolve())
        header = image.read_bytes()[:12]
        if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff')): raise ValueError('QR preview must be a PNG or JPEG image')
        if image.stat().st_size > 2 * 1024 * 1024: raise ValueError('QR preview image exceeds 2 MiB')
        preview['image'] = {'path': str(image.relative_to(folder)), 'sha256': sha(image)}
    preview['attached_at'] = now()
    target = folder / 'phone-preview.json'
    if target.exists() and (folder / 'video-publish-approval.json').exists(): raise ValueError('Confirmed preview is immutable; create a new version')
    previous = target.read_bytes() if target.exists() else None
    write(target, preview)
    try: checked_phone_preview(job, version)
    except Exception:
        if previous is None: target.unlink()
        else: target.write_bytes(previous)
        raise
    set_status(job, 'awaiting_video_phone_review')
    return {'job_id': job_id, 'version': int(folder.name[1:]), 'status': job['status'], 'published': False}


def confirm_video(job_id, version, source_message_id):
    active_path = ROOT / 'state/active-wecom-task.json'
    if not active_path.exists(): raise ValueError('Video confirmation requires an incoming enterprise WeChat message')
    active = read(active_path)
    if source_message_id != 'wecom:' + str(active.get('msgid', '')): raise ValueError('Confirmation does not match the current incoming message')
    inbox = ROOT.parent / 'wecom-bot-local/state/inbox' / (hashlib.sha256(active['msgid'].encode()).hexdigest() + '.json')
    incoming = read(inbox)
    target = incoming.get('user_id') if incoming.get('chattype') == 'single' else incoming.get('chatid')
    if incoming.get('msgid') != active['msgid'] or incoming.get('user_id') != active.get('user_id') or incoming.get('chattype') != active.get('chattype') or target != active.get('reply_to'):
        raise ValueError('Confirmation sender does not match its incoming receipt')
    text = re.sub(r'^(?:<@[^>]+>|@\S+)[\s\u2005]+', '', incoming.get('text', '').strip()).strip()
    explicit = re.fullmatch(r'(?:确认发布|发布|通过|[Oo][Kk])\s+(C\d{4,})-v([1-9]\d*)[。！!\s]*', text)
    plain = re.fullmatch(r'(?:[Oo][Kk]|确认发布|可以发布|发布吧)[。！!\s]*', text)
    if not explicit and not plain: raise ValueError('A real explicit video confirmation is required')
    if explicit:
        if job_id and (job_id != explicit[1] or int(version) != int(explicit[2])): raise ValueError('Confirmation names a different version')
        job_id, version = explicit[1], int(explicit[2])
    destination = {'provider': 'wecom', 'chatid': active.get('reply_to')}
    candidates = {}
    for path in (ROOT / 'outbox').glob('*.json'):
        item = read(path)
        if item.get('destination') != destination or item.get('status') in ('failed', 'cancelled', 'queued') or not item.get('phone_preview_sha256'): continue
        sent_at = item.get('phone_preview_sent_at')
        if not sent_at or not incoming.get('received_at') or datetime.fromisoformat(incoming['received_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(sent_at.replace('Z', '+00:00')): continue
        if job_id and (item.get('job_id') != job_id or item.get('version') != int(version)): continue
        job = get_job(item['job_id'])
        if item['version'] != job['version']: continue
        folder, preview = checked_phone_preview(job, item['version'])
        if item['phone_preview_sha256'] != sha(folder / 'phone-preview.json'): continue
        if not explicit and (folder / 'video-publish-approval.json').exists(): continue
        candidates[(job['id'], item['version'])] = (job, folder, preview, path)
    if len(candidates) != 1: raise ValueError('Name one current version whose phone preview was successfully sent in this conversation')
    job, folder, preview, delivery_path = next(iter(candidates.values()))
    approval_path = folder / 'video-publish-approval.json'
    if approval_path.exists(): return {'job_id': job['id'], 'version': int(folder.name[1:]), 'status': 'already_confirmed', 'published': False}
    approval = {'job_id': job['id'], 'version': int(folder.name[1:]), 'source_message_id': source_message_id,
                'reviewer': active['user_id'], 'destination': destination, 'at': now(),
                'manifest_sha256': sha(folder / 'manifest.json'), 'phone_preview_sha256': sha(folder / 'phone-preview.json'),
                'review_delivery': delivery_path.name, 'account': preview['account'], 'remote_record_id': preview['remote_record_id'],
                'draft_receipt': preview['draft_receipt'],
                'status': 'publication_authorized', 'published': False}
    write(approval_path, approval)
    set_status(job, 'video_publication_authorized')
    return {'job_id': job['id'], 'version': approval['version'], 'status': job['status'], 'publish_request': approval, 'published': False}


def deliver(job_id, version=None):
    job = get_job(job_id)
    folder, manifest = checked_manifest(job, version)
    for area in (('article', 'video') if job['kind'] == 'both' else (job['kind'],)):
        if manifest.get('qa', {}).get(area, {}).get('passed') is not True:
            raise ValueError(f'{area} validation has not passed')
    visual = read(folder / 'visual-review.json')
    if visual.get('checked') is not True or not visual.get('notes'): raise ValueError('Actual visual review is required')
    number = int(folder.name[1:])
    phone = None
    if 'review.mp4' in manifest['outputs']:
        if not (folder / 'phone-preview.json').exists():
            set_status(job, 'awaiting_video_phone_preview')
            return {'job_id': job_id, 'version': number, 'status': job['status'], 'queued': False,
                    'blocker': 'The real video-channel phone preview link or QR image is required before review delivery'}
        _, phone = checked_phone_preview(job, version)
    # Local TurboPush storage is independent of browser publishing and group delivery.
    local_import = ROOT/'turbopush_local.py'
    if CONFIG.get('turbopush_enabled') and 'review.mp4' in manifest['outputs'] and local_import.is_file() and (Path.home()/'.TurboPush/mcp.json').is_file():
        result = subprocess.run([CONFIG['article_python'], '-X', 'utf8', str(local_import), job_id, '--version', str(number)],
                                cwd=ROOT, capture_output=True, encoding='utf-8')
        (folder/'turbopush-import.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode: print('TurboPush local import needs attention; see this version\'s turbopush-import.log',file=sys.stderr)
    parts = []
    files = []
    images = []
    if phone:
        parts.append('视频号手机预览：' + (phone.get('url') or '请识别随附二维码，在手机查看。'))
        parts.append('目标账号：' + str(phone['account']))
        if phone.get('image'):
            images.append({'path': str(folder / phone['image']['path']), 'sha256': phone['image']['sha256']})
    if 'review.mp4' in manifest['outputs']:
        files.append({'path': str(folder / 'review.mp4'), 'sha256': manifest['outputs']['review.mp4']})
        parts.append('视频审片：MP4 文件附件随本任务送审，可下载保存。')
    official = folder / 'official-preview.json'
    if job['kind'] != 'video' and official.exists():
        parts.append('公众号草稿预览：' + official_url(read(official)['url']))
    elif job['kind'] != 'video':
        set_status(job, 'awaiting_official_preview')
        if not files: return {'job_id': job_id, 'status': job['status'], 'queued': False,
                              'blocker': 'Official WeChat draft preview link is not available'}
    text = f'{job_id}-v{number}｜{job["topic"]}\n' + '\n'.join(parts)
    destination = CONFIG.get('review_destination', {'provider': 'desktop_wechat', 'group': CONFIG['group']})
    active_path = ROOT/'state/active-wecom-task.json'
    source = read(active_path) if active_path.exists() else {}
    if source.get('chattype') in ('single', 'group') and source.get('reply_to'):
        destination = {'provider': 'wecom', 'chatid': source['reply_to']}
    text += (f'\n请先查看手机预览；确认后回复“确认发布 {job_id}-v{number}”，再进入视频发布。修改请回复“修改 {job_id} …”。'
             if phone else f'\n审核意见请 @ 机器人：修改 {job_id} …；通过 {job_id}-v{number}。')
    phone_hash = sha(folder / 'phone-preview.json') if phone else None
    media_type = 'file' if destination.get('provider') == 'wecom' else 'video'
    signature = hashlib.sha256(json.dumps({'text': text, 'files': files, 'images': images, 'phone_preview_sha256': phone_hash, 'destination': destination, 'media_type': media_type}, sort_keys=True).encode()).hexdigest()[:16]
    path = ROOT / 'outbox' / f'{job_id}-v{number}-{signature}.json'
    if not path.exists():
        # A later real article link should not cause a previously queued/sent video to be repeated.
        prior_files = {f['sha256'] for p in (ROOT / 'outbox').glob(f'{job_id}-v{number}-*.json')
                       for prior in [read(p)] if prior.get('destination', {'provider': 'desktop_wechat', 'group': prior.get('group')}) == destination
                       and prior.get('media_type', 'video') == media_type
                       and prior.get('status') not in ('failed', 'cancelled') for f in prior.get('files', [])}
        files = [f for f in files if f['sha256'] not in prior_files]
        write(path, {'job_id': job_id, 'version': number, 'group': CONFIG['group'], 'text': text,
                     'destination': destination, 'media_type': media_type, 'source_message_id': source.get('msgid'), 'files': files, 'images': images,
                     'phone_preview_sha256': phone_hash, 'status': 'queued', 'created_at': now(), 'steps': []})
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
    p = sub.add_parser('phone-preview'); p.add_argument('id'); p.add_argument('--version',type=int,required=True); p.add_argument('--receipt',required=True)
    args = parser.parse_args()
    if args.action == 'new': result = new_job(args.kind, args.topic)
    elif args.action == 'revise': result = revise(args.id, args.note)
    elif args.action == 'build': result = build(args.id, args.version)
    elif args.action == 'deliver': result = deliver(args.id, args.version)
    elif args.action == 'official': result = official_step(args.id,args.step,args.version)
    elif args.action == 'phone-preview': result = attach_phone_preview(args.id,args.version,args.receipt)
    else: result = status(args.id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
