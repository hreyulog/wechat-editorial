import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import official_drafts as drafts
from official_api import OfficialClient
import studio
import turbopush_local


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.saved_root=studio.ROOT;studio.ROOT=Path(self.tmp.name)
        for name in ('jobs','outbox','state'):(studio.ROOT/name).mkdir()
        self.job=studio.new_job('article','unit test fixture')
        self.folder=studio.version_dir(self.job);self.output=self.folder/'official';self.output.mkdir()
        (self.folder/'cover.png').write_bytes(b'fixture, not a real image')
        studio.write(self.folder/'manifest.json',{'sources':{},'outputs':{},'qa':{'article':{'passed':True}}})
        (self.output/'wechat.html').write_text('<p>unit test</p>',encoding='utf-8')
        studio.write(self.output/'payload.json',{'title':'fixture','content':'<p>unit test</p>'})
        self.binding={'version':1,'manifest_sha256':studio.sha(self.folder/'manifest.json'),
                      'payload_sha256':studio.sha(self.output/'payload.json'),'html_sha256':studio.sha(self.output/'wechat.html'),
                      'cover_sha256':studio.sha(self.folder/'cover.png')}
        studio.write(self.output/'binding.json',self.binding)
        studio.write(self.output/'visual-review.json',{'checked':True,'notes':'unit fixture','html_sha256':self.binding['html_sha256']})

    def tearDown(self):
        studio.ROOT=self.saved_root;self.tmp.cleanup()

    def test_changed_html_is_rejected_before_any_network_request(self):
        (self.output/'wechat.html').write_text('changed',encoding='utf-8')
        with patch.object(drafts,'OfficialClient') as client:
            with self.assertRaises(ValueError):drafts.submit(self.job['id'])
            client.assert_not_called()

    def test_unknown_creation_is_not_automatically_retried(self):
        studio.write(self.output/'receipt.json',{'state':'creating','payload_sha256':self.binding['payload_sha256']})
        with patch.object(drafts,'OfficialClient') as client:
            with self.assertRaises(ValueError):drafts.submit(self.job['id'])
            client.assert_not_called()

    def test_existing_media_id_only_reads_back_and_rejects_nonofficial_link(self):
        studio.write(self.output/'receipt.json',{'state':'created','media_id':'fixture-media','thumb_media_id':'fixture-cover'})
        with patch.object(drafts,'OfficialClient') as cls,patch.object(drafts,'publish_helpers') as helpers:
            client=cls.return_value;client.request.return_value={'news_item':[{'title':'fixture','url':'https://example.test/s'}]}
            with self.assertRaises(ValueError):drafts.submit(self.job['id'])
            helpers.return_value.create_draft.assert_not_called()
            helpers.return_value.upload_thumb.assert_not_called()
            client.request.assert_called_once_with('/draft/get',{'media_id':'fixture-media'})

    def test_publishing_endpoints_are_rejected(self):
        client=OfficialClient.__new__(OfficialClient)
        with self.assertRaises(ValueError):client.request('/freepublish/submit',{'media_id':'fixture'})
        with self.assertRaises(ValueError):turbopush_local.request_local('/sse/video/1',{})

    def test_successful_draft_without_requested_video_is_not_ready_for_review(self):
        studio.write(self.folder/'article.json',{'video_embed':{'source':'src/video.json'}})
        (self.folder/'src').mkdir(exist_ok=True)
        studio.write(self.folder/'src/video.json',{'vid':'apiv_fixture'})
        studio.write(self.output/'receipt.json',{'media_id':'fixture-media','thumb_media_id':'fixture-cover'})
        with patch.object(drafts,'OfficialClient') as cls,patch.object(drafts,'publish_helpers'):
            cls.return_value.request.return_value={'news_item':[{'title':'fixture','content':'<p>caption only</p>','url':'https://mp.weixin.qq.com/s/fixture'}]}
            result=drafts.submit(self.job['id'])
        self.assertFalse(result['ready_for_review'])
        self.assertFalse(result['video_player_preserved'])
        self.assertEqual(result['state'],'video_embedding_incomplete')
        self.assertFalse(result['published'])


if __name__=='__main__':unittest.main()
