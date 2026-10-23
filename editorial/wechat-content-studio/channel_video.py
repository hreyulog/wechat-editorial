"""Native Channels cards via the official draft API; never publishes a video."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def native_card_attributes(item):
    """Keep the actual editor component, including opaque native metadata."""
    from video_embed_check import video_tags
    raw = item.get('native_html', '')
    if not re.fullmatch(r'<mp-common-videosnap\b[^>]*>\s*</mp-common-videosnap>', raw, re.S | re.I):
        raise ValueError('A complete atomic native Channels card is required')
    if item.get('native_html_sha256') != hashlib.sha256(raw.encode('utf-8')).hexdigest():
        raise ValueError('Native Channels card bytes differ from the captured editor component')
    tags = video_tags(raw)
    if len(tags) != 1:
        raise ValueError('Only one native Channels component is allowed')
    attrs = tags[0]['attrs']
    if attrs.get('data-id') != item.get('export_id') or attrs.get('data-username') != item.get('username'):
        raise ValueError('Native Channels card identity differs from its descriptor')
    if any(key.lower().startswith('on') for key in attrs):
        raise ValueError('Event handlers are not native card data')
    if not re.fullmatch(r'\d+', attrs.get('data-nonceid', '')) or attrs.get('data-type') != 'video':
        raise ValueError('The captured native card is missing its real nonce or video type')
    for key, host in [('data-url', 'findermp.video.qq.com'), ('data-headimgurl', 'wx.qlogo.cn')]:
        url = urlparse(attrs.get(key, ''))
        if url.scheme != 'https' or url.hostname != host:
            raise ValueError('The captured native card is missing its official media metadata')
    for key in ('data-width', 'data-height'):
        if not attrs.get(key, '').isdigit() or not 0 < int(attrs[key]) <= 16384:
            raise ValueError('The captured native card dimensions are invalid')
    return attrs


def validate_descriptor(item):
    if not re.fullmatch(r'export/[A-Za-z0-9_-]+', item.get('export_id', '')):
        raise ValueError('A real Channels export ID is required, not a share URL or local record ID')
    if not re.fullmatch(r'v2_[A-Za-z0-9_-]+@finder', item.get('username', '')):
        raise ValueError('A real Channels username from the editor is required')
    if item.get('native_html') or item.get('require_complete_native_component'):
        native_card_attributes(item)
    return item


def descriptor_for(folder, article):
    source = (folder / article['channel_video']['source']).resolve()
    source.relative_to((folder / 'src').resolve())
    return validate_descriptor(json.loads(source.read_text(encoding='utf-8-sig')))


def card_html(item):
    validate_descriptor(item)
    if item.get('native_html'):
        return item['native_html']
    attrs = {'class': 'js_uneditable custom_select_card channels_iframe videosnap_video_iframe',
             'data-pluginname': 'mpvideosnap', 'data-type': 'video',
             'data-id': item['export_id'], 'data-username': item['username'],
             'data-nickname': item.get('nickname', ''), 'data-desc': item.get('description', '')}
    for name in ('width', 'height'):
        if name in item:
            value = int(item[name])
            if not 0 < value <= 16384:
                raise ValueError('Invalid video dimensions')
            attrs['data-' + name] = str(value)
    return '<mp-common-videosnap ' + ' '.join(
        key + '="' + html.escape(value, quote=True) + '"' for key, value in attrs.items()
    ) + '></mp-common-videosnap>'


def insert_channel_video(folder, article, content):
    if not article.get('channel_video'):
        return content
    if article.get('video_embed'):
        raise ValueError('Choose channel_video or video_embed, not both')
    from video_embed_check import video_tags
    item = descriptor_for(folder, article)
    existing = [tag for tag in video_tags(content) if tag['tag'] == 'mp-common-videosnap']
    if existing:
        if len(existing) == 1 and existing[0]['attrs'].get('data-id') == item['export_id'] and existing[0]['attrs'].get('data-username') == item['username']:
            if item.get('require_complete_native_component'):
                wanted = native_card_attributes(item)
                if any(existing[0]['attrs'].get(k) != wanted[k] for k in wanted):
                    raise ValueError('Existing card was simplified; restore the captured native component before saving')
            return content
        raise ValueError('Existing Channels card differs; do not silently replace it')
    anchor = article['channel_video'].get('after_paragraph', '')
    marker = html.escape(anchor, quote=False)
    if not anchor or content.count(marker) != 1:
        raise ValueError('A unique channel_video.after_paragraph is required')
    end = content.find('</p>', content.index(marker))
    if end < 0:
        raise ValueError('Video insertion paragraph is incomplete')
    end += 4
    return content[:end] + card_html(item) + content[end:]


def capture_component(detail, export_id):
    from video_embed_check import video_tags
    cards = [tag for article in detail.get('news_item', [])
             for tag in video_tags(article.get('content', ''))
             if tag['tag'] == 'mp-common-videosnap' and tag['attrs'].get('data-id') == export_id]
    if len(cards) != 1:
        raise ValueError('The requested card must occur exactly once in the official draft')
    attrs = cards[0]['attrs']
    item = {'export_id': attrs.get('data-id', ''), 'username': attrs.get('data-username', ''),
            'nickname': attrs.get('data-nickname', ''), 'description': attrs.get('data-desc', ''),
            'provenance': 'official_api_draft_get'}
    for key in ('width', 'height'):
        if attrs.get('data-' + key):
            item[key] = int(attrs['data-' + key])
    if all(attrs.get(key) for key in ('data-nonceid', 'data-url', 'data-headimgurl')):
        raw = cards[0]['raw_start'] + '</mp-common-videosnap>'
        item.update(native_html=raw, native_html_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                    require_complete_native_component=True)
    return validate_descriptor(item)


def adopt(job_id, export_id, version=None):
    # The user saved this same version manually. Bind its replacement card without
    # rewriting immutable local sources or round-tripping the remote HTML.
    from official_api import OfficialClient
    from studio import checked_manifest, get_job, read, write, sha, now, official_url
    from video_embed_check import verify_video_component
    folder, _ = checked_manifest(get_job(job_id), version)
    receipt = read(folder / 'official/receipt.json')
    if receipt['manifest_sha256'] != sha(folder / 'manifest.json'):
        raise ValueError('Draft receipt belongs to another version')
    detail = OfficialClient().request('/draft/get', {'media_id': receipt['media_id']})
    if len(detail.get('news_item', [])) != 1 or detail['news_item'][0]['title'] != read(folder / 'article.json')['title']:
        raise ValueError('The saved draft does not match this article')
    item = capture_component(detail, export_id)
    item.update(manifest_sha256=receipt['manifest_sha256'], media_id=receipt['media_id'], adopted_at=now())
    write(folder / 'official/channel-binding.json', item)
    write(folder / 'official/readback.json', detail)
    # Adoption changed the authoritative component. Refresh the linked metadata in
    # this same read-only operation so delivery cannot reuse the previous proof.
    check=verify_video_component(folder,read(folder/'article.json'),detail['news_item'][0].get('content',''))
    ready=check['preserved'] and check['complete_native_attributes_required']
    url=detail['news_item'][0].get('url','')
    if url.startswith('http://mp.weixin.qq.com/'):url='https://'+url[len('http://'):]
    url=official_url(url)
    receipt.update(state='preview_available' if ready else 'video_embedding_incomplete',readback_at=now(),
        readback_sha256=sha(folder/'official/readback.json'),video_component_check=check,
        video_component_preserved=check['preserved'],phone_playback_tested=False,verification_scope='official_draft_fields_only')
    receipt.pop('video_player_preserved',None)
    write(folder/'official/receipt.json',receipt)
    write(folder/'official-preview.json',{'url':url,'provenance':'official_api_draft_get','media_id':receipt['media_id'],
        'attached_at':now(),'manifest_sha256':receipt['manifest_sha256'],'readback_sha256':receipt['readback_sha256'],'valid':ready})
    return {'job_id': job_id, 'adopted': True, 'remote_write': False, 'phone_playback_tested': False}


def main():
    from official_api import OfficialClient
    from studio import read, write
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    capture = subs.add_parser('capture')
    capture.add_argument('--media-id', required=True); capture.add_argument('--export-id', required=True)
    capture.add_argument('--output', type=Path, required=True)
    adopt_parser = subs.add_parser('adopt')
    adopt_parser.add_argument('job_id'); adopt_parser.add_argument('--export-id', required=True)
    adopt_parser.add_argument('--version', type=int)
    render = subs.add_parser('render'); render.add_argument('folder', type=Path)
    args = parser.parse_args()
    client = None
    try:
        if args.action == 'adopt':
            result = adopt(args.job_id, args.export_id, args.version)
        elif args.action == 'capture':
            if args.output.exists():
                raise ValueError('Descriptor already exists; do not overwrite a version source')
            client = OfficialClient()
            detail = client.request('/draft/get', {'media_id': args.media_id})
            item = capture_component(detail, args.export_id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write(args.output, item)
            result = {'captured': True, 'remote_write': False}
        else:
            target = args.folder / 'wechat.html'
            original = target.read_text(encoding='utf-8')
            content = insert_channel_video(args.folder, read(args.folder/'article.json'), original)
            if content != original:
                target.write_text(content, encoding='utf-8')
            result = {'inserted': content != original, 'remote_write': False}
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        message = client.sanitize(error) if client else str(error)
        print(json.dumps({'ok': False, 'error': message}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
