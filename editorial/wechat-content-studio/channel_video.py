"""Native Channels cards via the official draft API; never publishes a video."""
import argparse
import html
import json
import re
from pathlib import Path


def validate_descriptor(item):
    if not re.fullmatch(r'export/[A-Za-z0-9_-]+', item.get('export_id', '')):
        raise ValueError('A real Channels export ID is required, not a share URL or local record ID')
    if not re.fullmatch(r'v2_[A-Za-z0-9_-]+@finder', item.get('username', '')):
        raise ValueError('A real Channels username from the editor is required')
    return item


def descriptor_for(folder, article):
    source = (folder / article['channel_video']['source']).resolve()
    source.relative_to((folder / 'src').resolve())
    return validate_descriptor(json.loads(source.read_text(encoding='utf-8-sig')))


def card_html(item):
    validate_descriptor(item)
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
    return validate_descriptor(item)


def adopt(job_id, export_id, version=None):
    # The user saved this same version manually. Bind its replacement card without
    # rewriting immutable local sources or round-tripping the remote HTML.
    from official_api import OfficialClient
    from studio import checked_manifest, get_job, read, write, sha, now
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
