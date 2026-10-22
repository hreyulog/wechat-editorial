import json
import tempfile
import unittest
from pathlib import Path
import studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = studio.ROOT
        studio.ROOT = Path(self.temp.name) / 'wechat-content-studio'
        studio.ROOT.mkdir()
        for name in ('jobs','outbox','state'): (studio.ROOT/name).mkdir()

    def tearDown(self):
        studio.ROOT = self.original
        self.temp.cleanup()

    def fixture(self, kind):
        job=studio.new_job(kind,'fixture')
        folder=studio.version_dir(job)
        artifact=folder/('review.mp4' if kind=='video' else 'article.html')
        artifact.write_bytes(b'unit test fixture, not a real delivery')
        studio.write(folder/'manifest.json',{'sources':{},'outputs':{artifact.name:studio.sha(artifact)},'qa':{kind:{'passed':True}}})
        studio.write(folder/'visual-review.json',{'checked':True,'notes':'fixture review'})
        if kind == 'video':
            studio.write(folder/'turbopush-remote.json',{'job_id':job['id'],'version':1,'syncDraft':True,
                'published':False,'public_publish_attempted':False,'record_success':True,'record_status':4,
                'record_id':'fixture-draft-record','account_name':'fixture-account','account_id':1,
                'video_sha256':studio.sha(artifact),'verified_via':['turbo_push.get_record_info']})
            receipt = folder/'remote-phone-preview.json'
            studio.write(receipt,{'provenance':'video_channel_phone_preview','url':'https://channels.weixin.qq.com/preview/fixture',
                                  'account':'fixture-account','remote_record_id':'fixture-draft','draft_receipt':'turbopush-remote.json',
                                  'video_sha256':studio.sha(artifact)})
            studio.attach_phone_preview(job['id'],1,receipt)
        return job,folder,artifact

    def confirmation(self, text, user='reviewer', msgid='confirmation-1'):
        active={'msgid':msgid,'user_id':user,'chattype':'single','reply_to':user}
        studio.write(studio.ROOT/'state/active-wecom-task.json',active)
        inbox=studio.ROOT.parent/'wecom-bot-local/state/inbox'
        inbox.mkdir(parents=True,exist_ok=True)
        studio.write(inbox/(studio.hashlib.sha256(msgid.encode()).hexdigest()+'.json'),
                     {'msgid':msgid,'user_id':user,'chattype':'single','text':text,'received_at':studio.now()})
        return 'wecom:'+msgid

    def sent_preview(self, job):
        self.confirmation('make a video',msgid='source-task')
        delivery=studio.deliver(job['id'])
        path=Path(delivery['outbox'])
        studio.write(path,{**studio.read(path),'status':'sent','sent_at':'2000-01-01T00:00:00+00:00','phone_preview_sent_at':'2000-01-01T00:00:00+00:00'})
        return path

    def test_video_waits_for_real_phone_preview(self):
        job,folder,_=self.fixture('video')
        (folder/'phone-preview.json').unlink()
        result=studio.deliver(job['id'])
        self.assertFalse(result['queued'])
        self.assertEqual(result['status'],'awaiting_video_phone_preview')
        self.assertEqual(list((studio.ROOT/'outbox').glob('*')),[])

    def test_phone_preview_rejects_nonofficial_and_admin_links(self):
        job,folder,_=self.fixture('video')
        for url in ('http://127.0.0.1/video','https://example.com/video','https://channels.weixin.qq.com/platform'):
            source=folder/'invalid-preview.json'
            studio.write(source,{'provenance':'video_channel_phone_preview','url':url,'account':'fixture-account','remote_record_id':'fixture',
                                 'video_sha256':studio.sha(folder/'review.mp4'),'draft_receipt':'turbopush-remote.json'})
            with self.assertRaisesRegex(ValueError,'official HTTPS|not a phone preview'):studio.attach_phone_preview(job['id'],1,source)
        self.assertEqual(studio.checked_phone_preview(job,1)[1]['account'],'fixture-account')

    def test_video_confirmation_is_bound_to_delivered_preview_and_real_sender(self):
        job,folder,_=self.fixture('video')
        source=self.confirmation('确认发布 '+job['id']+'-v1')
        with self.assertRaises(ValueError):studio.confirm_video(job['id'],1,source)
        self.sent_preview(job)
        source=self.confirmation('确认发布 '+job['id']+'-v1',user='someone-else')
        with self.assertRaises(ValueError):studio.confirm_video(job['id'],1,source)
        source=self.confirmation('确认发布 '+job['id']+'-v1')
        result=studio.confirm_video(job['id'],1,source)
        self.assertFalse(result['published'])
        self.assertEqual(result['publish_request']['account'],'fixture-account')
        self.assertEqual(result['publish_request']['manifest_sha256'],studio.sha(folder/'manifest.json'))
        self.assertEqual(studio.confirm_video(job['id'],1,source)['status'],'already_confirmed')

    def test_plain_ok_requires_one_current_preview_in_same_conversation(self):
        first,_,_=self.fixture('video');self.sent_preview(first)
        second,_,_=self.fixture('video');self.sent_preview(second)
        source=self.confirmation('ok')
        with self.assertRaises(ValueError):studio.confirm_video(None,None,source)
        studio.revise(first['id'],'replace the old version')
        source=self.confirmation('ok')
        result=studio.confirm_video(None,None,source)
        self.assertEqual(result['job_id'],second['id'])
        source=self.confirmation('确认发布 '+first['id']+'-v1',msgid='old-version')
        with self.assertRaises(ValueError):studio.confirm_video(first['id'],1,source)

    def test_confirmation_rejects_changed_or_expired_preview(self):
        job,folder,_=self.fixture('video');self.sent_preview(job)
        source=self.confirmation('确认发布 '+job['id']+'-v1')
        preview=studio.read(folder/'phone-preview.json')
        studio.write(folder/'phone-preview.json',{**preview,'url':'https://channels.weixin.qq.com/preview/replaced'})
        with self.assertRaises(ValueError):studio.confirm_video(job['id'],1,source)
        studio.write(folder/'phone-preview.json',{**preview,'expires_at':'2000-01-01T00:00:00+00:00'})
        with self.assertRaises(ValueError):studio.confirm_video(job['id'],1,source)

    def test_phone_preview_requires_a_successful_draft_for_the_same_video_and_account(self):
        job,folder,_=self.fixture('video')
        original=studio.read(folder/'turbopush-remote.json')
        source=folder/'remote-phone-preview.json'
        for patch in ({'record_success':False},{'syncDraft':False},{'published':True},
                      {'video_sha256':'wrong-hash'},{'account_name':'wrong-account'}):
            studio.write(folder/'turbopush-remote.json',{**original,**patch})
            with self.assertRaises(ValueError):studio.attach_phone_preview(job['id'],1,source)

    def test_article_does_not_fake_an_official_link(self):
        job,folder,_=self.fixture('article')
        result=studio.deliver(job['id'])
        self.assertFalse(result['queued'])
        self.assertEqual(result['status'],'awaiting_official_preview')
        self.assertEqual(list((studio.ROOT/'outbox').glob('*')),[])
        with self.assertRaises(ValueError): studio.review(job['id'],1,'fixture-message')

    def test_admin_local_and_foreign_urls_rejected(self):
        for url in ('http://mp.weixin.qq.com/s?x=1','http://localhost/a','https://mp.weixin.qq.com/cgi-bin/home','https://mp.weixin.qq.com.evil.test/s?x=1'):
            with self.assertRaises(ValueError): studio.official_url(url)

    def test_delivery_is_idempotent_and_changed_artifacts_rejected(self):
        job,folder,artifact=self.fixture('video')
        first=studio.deliver(job['id']); second=studio.deliver(job['id'])
        self.assertEqual(first['outbox'],second['outbox'])
        self.assertEqual(len(list((studio.ROOT/'outbox').glob('*'))),1)
        artifact.write_bytes(b'changed')
        with self.assertRaises(ValueError): studio.deliver(job['id'])

    def test_failed_qa_cannot_be_delivered(self):
        job,folder,_=self.fixture('video')
        manifest=studio.read(folder/'manifest.json');manifest['qa']['video']['passed']=False
        studio.write(folder/'manifest.json',manifest)
        with self.assertRaises(ValueError): studio.deliver(job['id'])

    def test_switch_destination_does_not_suppress_native_video(self):
        job,folder,_=self.fixture('video')
        original=studio.CONFIG.copy()
        try:
            studio.CONFIG['review_destination']={'provider':'desktop_wechat','group':'legacy'}
            first=studio.deliver(job['id'])
            studio.CONFIG['review_destination']={'provider':'wecom','chatid':'new-group'}
            second=studio.deliver(job['id'])
            self.assertNotEqual(first['outbox'],second['outbox'])
            self.assertEqual(len(studio.read(Path(second['outbox']))['files']),1)
            self.assertEqual(studio.deliver(job['id'])['outbox'],second['outbox'])
        finally:
            studio.CONFIG.clear();studio.CONFIG.update(original)

    def test_revisions_keep_previous_artifacts_and_reset_approval(self):
        job,folder,_=self.fixture('video')
        studio.review(job['id'],1,'fixture-user-message')
        revised=studio.revise(job['id'],'shorten opening')
        self.assertEqual(revised['version'],2)
        self.assertTrue((folder/'review.json').exists())
        self.assertFalse((studio.version_dir(revised)/'review.json').exists())
        self.assertFalse((studio.version_dir(revised)/'review.mp4').exists())
        self.assertFalse(revised['publish_enabled'])

if __name__=='__main__': unittest.main()
