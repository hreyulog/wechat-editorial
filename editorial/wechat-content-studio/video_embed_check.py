"""Verify actual draft/get video components, never local placeholder markup."""
import json
import hashlib
from html.parser import HTMLParser
from pathlib import Path


class VideoTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag in ('mp-common-videosnap', 'iframe', 'video', 'mpvideo'):
            self.tags.append({'tag': tag, 'attrs': dict(attrs), 'raw_start': self.get_starttag_text()})


def video_tags(content):
    parser = VideoTags()
    parser.feed(content)
    return parser.tags


def channels_requirement(descriptor):
    expected = {'kind': 'channels', 'id': descriptor['export_id'], 'username': descriptor.get('username', '')}
    if descriptor.get('native_html') or descriptor.get('require_complete_native_component'):
        from channel_video import native_card_attributes
        attrs = native_card_attributes(descriptor)
        expected['native_attributes'] = {key: value for key, value in attrs.items() if key.startswith('data-')}
    return expected


def video_requirement(folder, article):
    binding = folder / 'official/channel-binding.json'
    if binding.is_file():
        descriptor = json.loads(binding.read_text(encoding='utf-8-sig'))
        receipt = json.loads((folder / 'official/receipt.json').read_text(encoding='utf-8-sig'))
        digest = hashlib.sha256((folder / 'manifest.json').read_bytes()).hexdigest()
        if descriptor.get('manifest_sha256') != digest or descriptor.get('media_id') != receipt.get('media_id'):
            raise ValueError('Manually saved Channels binding belongs to another draft or version')
        from channel_video import validate_descriptor
        validate_descriptor(descriptor)
        return channels_requirement(descriptor)
    setting = article.get('channel_video') or article.get('video_embed')
    if not setting:
        return None
    source = (folder / setting['source']).resolve()
    source.relative_to((folder / 'src').resolve())
    descriptor = json.loads(source.read_text(encoding='utf-8-sig'))
    if article.get('channel_video'):
        if not descriptor.get('export_id', '').startswith('export/'):
            raise ValueError('A real video-channel component identity is required')
        return channels_requirement(descriptor)
    if not descriptor.get('vid'):
        raise ValueError('A real official video identity is required')
    return {'kind': 'official_video', 'id': descriptor['vid']}


def verify_video_component(folder, article, content):
    expected = video_requirement(folder, article)
    if expected is None:
        return {'required': False, 'preserved': True, 'phone_playback_tested': False}
    found = video_tags(content)
    if expected['kind'] == 'channels':
        preserved = any(item['tag'] == 'mp-common-videosnap'
                        and item['attrs'].get('data-id') == expected['id']
                        and (not expected['username'] or item['attrs'].get('data-username') == expected['username'])
                        and all(item['attrs'].get(key) == value for key, value in expected.get('native_attributes', {}).items())
                        for item in found)
    else:
        preserved = any(item['tag'] in ('iframe', 'video', 'mpvideo')
                        and expected['id'] in (item['attrs'].get('data-mpvid'), item['attrs'].get('vid'),
                                              item['attrs'].get('data-vid'))
                        for item in found)
    return {'required': True, 'kind': expected['kind'], 'expected_id': expected['id'],
            'preserved': preserved, 'complete_native_attributes_required': bool(expected.get('native_attributes')),
            'phone_playback_tested': False, 'published_page_playback_tested': False}


def require_deliverable_video(folder, article, manifest_sha256):
    expected = video_requirement(folder, article)
    if expected is None:
        return
    receipt = json.loads((folder / 'official/receipt.json').read_text(encoding='utf-8-sig'))
    if receipt.get('manifest_sha256') != manifest_sha256:
        raise ValueError('Video draft receipt belongs to another content version')
    if expected['kind'] == 'channels' and not expected.get('native_attributes'):
        raise ValueError('视频尚未插入完整原生组件：仅有作品 ID 不足以送审或发表，请重新 capture 真实编辑器卡片。')
    detail = json.loads((folder / 'official/readback.json').read_text(encoding='utf-8-sig'))
    items = detail.get('news_item') or []
    if len(items) != 1 or not verify_video_component(folder, article, items[0].get('content', ''))['preserved']:
        raise ValueError('官方草稿未保留所需视频组件；视频尚未插入，不能当作完整成稿送审。')
