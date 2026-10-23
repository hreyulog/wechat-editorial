import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channel_video import card_html, insert_channel_video, capture_component, adopt
from video_embed_check import verify_video_component, video_tags
import studio


class ChannelVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / 'v1'
        self.folder.mkdir()
        (self.folder/'src').mkdir()
        self.descriptor = {'export_id':'export/actual-work', 'username':'v2_example@finder',
                           'nickname':'示例账号', 'description':'A < B & "quoted"', 'width':1080, 'height':1440}
        studio.write(self.folder/'src/channel.json', self.descriptor)
        self.article = {'channel_video':{'source':'src/channel.json', 'after_paragraph':'在这里看视频。'}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_insert_preserves_body_styles_and_is_idempotent(self):
        original = '<p style="font-family:\'宋体\';color:#123">在这里看视频。</p><p>后文</p>'
        inserted = insert_channel_video(self.folder, self.article, original)
        self.assertEqual(inserted.replace(card_html(self.descriptor), ''), original)
        self.assertTrue(verify_video_component(self.folder, self.article, inserted)['preserved'])
        self.assertEqual(insert_channel_video(self.folder, self.article, inserted), inserted)
        self.assertEqual(video_tags(inserted)[0]['attrs']['data-desc'], self.descriptor['description'])

    def test_unknown_or_ambiguous_anchor_and_wrong_existing_card_fail(self):
        for content in ('<p>other</p>', '<p>在这里看视频。</p>'*2,
                        '<mp-common-videosnap data-id="export/other"></mp-common-videosnap>'):
            with self.assertRaises(ValueError):
                insert_channel_video(self.folder, self.article, content)

    def test_share_link_missing_username_and_path_escape_fail(self):
        for change in ({'export_id':'https://weixin.qq.com/sph/example'}, {'username':''}):
            with self.assertRaises(ValueError):
                card_html({**self.descriptor, **change})
        with self.assertRaises(ValueError):
            insert_channel_video(self.folder, {'channel_video':{'source':'../outside.json'}}, '<p>x</p>')

    def test_capture_selects_exact_work_and_excludes_signed_fields(self):
        markup = card_html(self.descriptor).replace(' data-type=', ' data-url="https://example.test/?token=private" data-nonceid="private" data-type=')
        detail = {'news_item':[{'content':markup}]}
        item = capture_component(detail, self.descriptor['export_id'])
        self.assertEqual(item['username'], self.descriptor['username'])
        self.assertNotIn('private', json.dumps(item))
        for content in ('', markup+markup):
            with self.assertRaises(ValueError):
                capture_component({'news_item':[{'content':content}]}, self.descriptor['export_id'])

    def test_prepare_inserts_native_card_and_binds_the_exact_html(self):
        import official_drafts as drafts
        (self.folder/'cover.png').write_bytes(b'fixture')
        studio.write(self.folder/'manifest.json', {})
        studio.write(self.folder/'article.json', {**self.article, 'title':'fixture'})
        (self.folder/'wechat.html').write_text('<p>在这里看视频。</p>', encoding='utf-8')
        with patch.object(drafts, 'get_job', return_value={'kind':'article'}), patch.object(drafts, 'checked_manifest',
                return_value=(self.folder, {'qa':{'article':{'passed':True}}, 'outputs':{'wechat.html':'fixture'}})):
            output, binding = drafts.prepare('C0001')
        payload = studio.read(output/'payload.json')
        self.assertTrue(verify_video_component(self.folder, self.article, payload['content'])['preserved'])
        self.assertEqual(binding['html_sha256'], studio.sha(output/'wechat.html'))
        self.assertEqual(payload['content'], (output/'wechat.html').read_text(encoding='utf-8'))

    def test_complete_native_component_survives_capture_and_rebuild_verbatim(self):
        raw=card_html(self.descriptor).replace(' data-type=',
            ' data-nonceid="123456789" data-url="https://findermp.video.qq.com/path?token=opaque" '
            'data-headimgurl="https://wx.qlogo.cn/avatar" data-extra="keep-me" data-type=')
        captured=capture_component({'news_item':[{'content':raw}]},self.descriptor['export_id'])
        self.assertEqual(captured['native_html'],raw)
        self.assertEqual(card_html(captured),raw)
        studio.write(self.folder/'src/channel.json',captured)
        self.assertTrue(verify_video_component(self.folder,self.article,raw)['preserved'])
        for attribute in ('data-nonceid="123456789"','data-url="https://findermp.video.qq.com/path?token=opaque"',
                          'data-extra="keep-me"','data-width="1080"'):
            simplified=raw.replace(attribute,'')
            self.assertFalse(verify_video_component(self.folder,self.article,simplified)['preserved'])
            with self.assertRaisesRegex(ValueError,'simplified'):
                insert_channel_video(self.folder,self.article,simplified)

    def test_native_card_identity_hash_and_unsafe_metadata_are_rejected(self):
        raw=card_html(self.descriptor).replace(' data-type=',
            ' data-nonceid="123456789" data-url="https://findermp.video.qq.com/path" '
            'data-headimgurl="https://wx.qlogo.cn/avatar" data-type=')
        captured=capture_component({'news_item':[{'content':raw}]},self.descriptor['export_id'])
        with self.assertRaises(ValueError):card_html({**captured,'native_html':raw+' '})
        for changed in (raw.replace('findermp.video.qq.com','attacker.test'),raw.replace(' data-type=',' onclick="bad()" data-type=')):
            with self.assertRaises(ValueError):
                card_html({**captured,'native_html':changed,'native_html_sha256':hashlib.sha256(changed.encode()).hexdigest()})

    def test_manual_adoption_is_read_only_and_bound_to_manifest_and_media(self):
        (self.folder/'official').mkdir()
        studio.write(self.folder/'manifest.json', {'sources':{},'outputs':{}})
        digest = studio.sha(self.folder/'manifest.json')
        studio.write(self.folder/'article.json', {'title':'fixture','video_embed':{'source':'src/old.json'}})
        studio.write(self.folder/'official/receipt.json', {'media_id':'same-draft','manifest_sha256':digest})
        article = studio.read(self.folder/'article.json')
        detail = {'news_item':[{'title':'fixture','content':card_html(self.descriptor),'url':'https://mp.weixin.qq.com/s?fixture=1'}]}
        with patch.object(studio,'get_job',return_value={}), patch.object(studio,'checked_manifest',return_value=(self.folder,{})), patch('official_api.OfficialClient') as client:
            client.return_value.request.return_value = detail
            result = adopt('C0001', self.descriptor['export_id'])
            client.return_value.request.assert_called_once_with('/draft/get', {'media_id':'same-draft'})
        self.assertFalse(result['remote_write'])
        self.assertTrue(verify_video_component(self.folder, article, detail['news_item'][0]['content'])['preserved'])
        studio.write(self.folder/'manifest.json', {'changed':True})
        with self.assertRaisesRegex(ValueError,'another draft or version'):
            verify_video_component(self.folder, article, detail['news_item'][0]['content'])


if __name__ == '__main__':
    unittest.main()
