import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from draft_identity import read_exact,check_local_binding,refresh_native_readback,digest,mobile_playback_confirmed
from official_api import ApiError
from studio import write


class DraftIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        (self.folder/'official').mkdir();(self.folder/'src').mkdir()
        raw=('<mp-common-videosnap data-id="export/real" data-username="v2_real@finder" '
             'data-nonceid="123" data-type="video" data-width="1080" data-height="1920" '
             'data-url="https://findermp.video.qq.com/video" data-headimgurl="https://wx.qlogo.cn/avatar"></mp-common-videosnap>')
        write(self.folder/'src/card.json',{'export_id':'export/real','username':'v2_real@finder',
            'native_html':raw,'native_html_sha256':hashlib.sha256(raw.encode()).hexdigest()})
        self.article={'title':'same title','channel_video':{'source':'src/card.json'}}
        self.detail={'news_item':[{'title':'same title','content':'<p>Body</p>'+raw,'url':'https://mp.weixin.qq.com/s?tempkey=fixture'}]}
        write(self.folder/'official/readback.json',self.detail)
        self.receipt={'media_id':'exact-media','manifest_sha256':'manifest','state':'preview_available'}
        write(self.folder/'official/receipt.json',self.receipt)
        self.preview={'url':self.detail['news_item'][0]['url'],'media_id':'exact-media','manifest_sha256':'manifest',
            'readback_sha256':digest(self.folder/'official/readback.json')}
        write(self.folder/'official-preview.json',self.preview)

    def tearDown(self):self.tmp.cleanup()

    def test_preview_cannot_point_at_a_same_title_substitute_or_changed_readback(self):
        for change in ({'media_id':'another-same-title-media'},{'valid':False},{'manifest_sha256':'other'},{'readback_sha256':'old'}):
            write(self.folder/'official-preview.json',{**self.preview,**change})
            with self.assertRaises(ValueError):check_local_binding(self.folder,self.receipt,'manifest')

    def test_missing_draft_never_searches_or_creates_a_substitute(self):
        client=Mock();client.request.side_effect=ApiError(40007,'invalid media_id')
        with patch('official_api.OfficialClient',return_value=client):
            with self.assertRaisesRegex(ValueError,'no same-title draft'):refresh_native_readback(self.folder,self.article,self.receipt,'manifest')
        client.request.assert_called_once_with('/draft/get',{'media_id':'exact-media'})
        preview=json.loads((self.folder/'official-preview.json').read_text())
        self.assertFalse(preview['valid']);self.assertEqual(preview['media_id'],'exact-media')
        receipt=json.loads((self.folder/'official/receipt.json').read_text())
        self.assertEqual(receipt['state'],'draft_unavailable')

    def test_refresh_is_read_only_and_does_not_claim_mobile_playback(self):
        client=Mock();client.request.return_value=self.detail
        with patch('official_api.OfficialClient',return_value=client):
            result=refresh_native_readback(self.folder,self.article,self.receipt,'manifest')
        client.request.assert_called_once_with('/draft/get',{'media_id':'exact-media'})
        self.assertTrue(result['preserved']);self.assertFalse(result['phone_playback_tested'])
        self.assertEqual(result['verification_scope'],'official_draft_fields_only')
        check_local_binding(self.folder,json.loads((self.folder/'official/receipt.json').read_text()),'manifest')

    def test_edits_in_the_real_draft_are_not_overwritten_or_silently_adopted(self):
        client=Mock();client.request.return_value={'news_item':[{**self.detail['news_item'][0],'content':'<p>Edited by user</p>'}]}
        original=(self.folder/'official/readback.json').read_bytes()
        with patch('official_api.OfficialClient',return_value=client):
            with self.assertRaisesRegex(ValueError,'new version'):refresh_native_readback(self.folder,self.article,self.receipt,'manifest')
        self.assertEqual((self.folder/'official/readback.json').read_bytes(),original)
        self.assertEqual(client.request.call_count,1)

    def test_mobile_confirmation_is_bound_to_the_exact_draft_version_and_content(self):
        content=self.detail['news_item'][0]['content']
        write(self.folder/'official/mobile-playback-confirmation.json',{'user_confirmed':True,'confirmed_at':'2026-10-23T12:00:00Z',
            'media_id':'exact-media','manifest_sha256':'manifest','content_sha256':hashlib.sha256(content.encode()).hexdigest()})
        self.assertTrue(mobile_playback_confirmed(self.folder,'exact-media','manifest',content))
        for media,version,body in [('different-media','manifest',content),('exact-media','new-version',content),('exact-media','manifest',content+' changed')]:
            self.assertFalse(mobile_playback_confirmed(self.folder,media,version,body))


if __name__=='__main__':unittest.main()
