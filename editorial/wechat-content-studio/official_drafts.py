"""Version-bound official drafts, reusing aws-wechat-article-publish's payload helpers."""
import argparse
import importlib.util
import json
import mimetypes
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from official_api import OfficialClient, ApiError
from video_embed_check import verify_video_component
from channel_video import insert_channel_video
from studio import CONFIG, ROOT, checked_manifest, get_job, now, official_url, read, sha, write, set_status


def prepare(job_id, version=None):
    job = get_job(job_id)
    folder, manifest = checked_manifest(job, version)
    if job['kind'] == 'video' or manifest['qa'].get('article', {}).get('passed') is not True:
        raise ValueError('A validated article is required')
    output = folder / 'official'; output.mkdir(exist_ok=True)
    source = folder / 'wechat.html'
    if source.is_file() and 'wechat.html' in manifest['outputs']:
        html = source.read_text(encoding='utf-8')
    else:
        target = output / 'wechat.html'
        formatter = Path(CONFIG['article_skills']) / 'skills/aws-wechat-article-formatting/scripts/format.py'
        result = subprocess.run([CONFIG['article_python'], '-X', 'utf8', str(formatter), str(folder/'article.md'),
                                 '--theme', '亲和', '--scheme', '松绿', '-o', str(target)],
                                cwd=CONFIG['article_skills'], capture_output=True, encoding='utf-8', check=True)
        (output/'format.log').write_text(result.stdout+result.stderr, encoding='utf-8')
        html = target.read_text(encoding='utf-8')
    (output/'wechat.html').write_text(html, encoding='utf-8')
    article = read(folder/'article.json')
    html = insert_channel_video(folder, article, html)
    (output/'wechat.html').write_text(html, encoding='utf-8')
    if not article['title'] or len(article['title']) > 32: raise ValueError('Title must be 1–32 characters')
    if len(html) > 20000 or any(x in html.lower() for x in ('<script', 'placeholder')):
        raise ValueError('Article HTML is not ready for a real draft')
    payload = {'title':article['title'], 'author':article.get('author',''),
               'digest':article.get('subtitle','')[:128], 'content':html,
               'need_open_comment':0, 'only_fans_can_comment':0}
    write(output/'payload.json',payload)
    binding = {'job_id':job_id,'version':int(folder.name[1:]),'prepared_at':now(),
               'manifest_sha256':sha(folder/'manifest.json'),'payload_sha256':sha(output/'payload.json'),
               'html_sha256':sha(output/'wechat.html'),'cover_sha256':sha(folder/'cover.png')}
    write(output/'binding.json', binding)
    return output, binding


def publish_helpers(client):
    script = Path(CONFIG['article_skills'])/'skills/aws-wechat-article-publish/scripts/publish.py'
    spec = importlib.util.spec_from_file_location('draft_only_publish_helpers',script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.API_BASE = 'https://api.weixin.qq.com'
    def endpoint(url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'api.weixin.qq.com': raise ValueError('Unofficial API refused')
        return parsed.path.removeprefix('/cgi-bin')
    module._api_post_json = lambda url, body: client.request(endpoint(url), body)
    def upload(url, file_path, field_name='media'):
        path = Path(file_path)
        boundary = 'WeChatDraft'+uuid.uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'
                f'Content-Type: {mimetypes.guess_type(path.name)[0] or "application/octet-stream"}\r\n\r\n').encode()
        data += path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        return client.request(endpoint(url),data=data,content_type='multipart/form-data; boundary='+boundary,query={'type':'image'})
    module._upload_file = upload
    return module


def submit(job_id, version=None):
    job = get_job(job_id); folder, _ = checked_manifest(job,version)
    output = folder/'official'; binding = read(output/'binding.json')
    for candidate, expected in [(folder/'manifest.json',binding['manifest_sha256']),
                                (output/'payload.json',binding['payload_sha256']),
                                (output/'wechat.html',binding['html_sha256']),
                                (folder/'cover.png',binding['cover_sha256'])]:
        if sha(candidate) != expected: raise ValueError('Prepared article changed; prepare and review again')
    visual = read(output/'visual-review.json')
    if visual.get('checked') is not True or not visual.get('notes') or visual.get('html_sha256') != binding['html_sha256']:
        raise ValueError('Review the exact official HTML before upload')
    receipt_path = output/'receipt.json'
    receipt = read(receipt_path) if receipt_path.exists() else {'job_id':job_id,'version':binding['version'],'published':False}
    if receipt.get('payload_sha256') not in (None,binding['payload_sha256']): raise ValueError('Existing draft has a different payload')
    if receipt.get('state') in ('creating','outcome_unknown') and not receipt.get('media_id'):
        raise ValueError('Previous draft creation outcome is unknown; inspect the draft box before retrying')
    client = OfficialClient(); token = client.get_token(); helpers = publish_helpers(client)
    if not receipt.get('thumb_media_id'):
        thumbnail = helpers.upload_thumb(token,str(folder/'cover.png'))
        receipt['thumb_media_id'] = thumbnail['media_id']; write(receipt_path,receipt)
    if not receipt.get('media_id'):
        article = read(output/'payload.json'); article['thumb_media_id'] = receipt['thumb_media_id']
        article.update(helpers._cover_crops(str(folder/'cover.png'),{}))
        receipt.update(state='creating',payload_sha256=binding['payload_sha256'],manifest_sha256=binding['manifest_sha256'],started_at=now())
        write(receipt_path,receipt)
        try: media_id = helpers.create_draft(token,[article])
        except BaseException as error:
            receipt['state'] = 'rejected' if isinstance(error,ApiError) and isinstance(error.code,int) else 'outcome_unknown'
            write(receipt_path,receipt); raise
        receipt.update(media_id=media_id,state='created',created_at=now()); write(receipt_path,receipt)
    detail = client.request('/draft/get',{'media_id':receipt['media_id']})
    items = detail.get('news_item') or []
    if len(items) != 1 or items[0].get('title') != read(output/'payload.json')['title']:
        raise ValueError('Official readback does not match the submitted article')
    write(output/'readback.json',detail)
    source_article = read(folder/'article.json') if (folder/'article.json').is_file() else {}
    video_check = verify_video_component(folder, source_article, items[0].get('content', ''))
    if video_check['required']:
        receipt['video_player_preserved'] = video_check['preserved']
        receipt['video_component_check'] = video_check
        write(output/'video-readback.json', video_check)
    ready = video_check['preserved']
    raw_url = items[0].get('url','')
    parsed = urlparse(raw_url)
    if parsed.scheme == 'http' and parsed.hostname == 'mp.weixin.qq.com': raw_url = urlunparse(parsed._replace(scheme='https'))
    url = official_url(raw_url)
    receipt.update(state='preview_available' if ready else 'video_embedding_incomplete',preview_url=url,readback_at=now()); write(receipt_path,receipt)
    preview = {'url':url,'provenance':'official_api_draft_get','media_id':receipt['media_id'],
               'attached_at':now(),'manifest_sha256':binding['manifest_sha256'],'readback_sha256':sha(output/'readback.json')}
    write(folder/'official-preview.json',preview)
    if ready and job.get('status') == 'awaiting_video_embed' and job.get('version') == binding['version']:
        set_status(job, 'awaiting_review')
    return {'job_id':job_id,'version':binding['version'],'state':receipt['state'],'url':url,'published':False,
            'ready_for_review':ready,
            **({'video_player_preserved':ready,'phone_playback_tested':False} if video_check['required'] else {})}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','submit']);parser.add_argument('id');parser.add_argument('--version',type=int)
    args=parser.parse_args()
    try:
        result = prepare(args.id,args.version)[1] if args.action=='prepare' else submit(args.id,args.version)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ApiError,ValueError,FileNotFoundError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));sys.exit(1)
