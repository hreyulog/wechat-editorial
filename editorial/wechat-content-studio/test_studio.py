import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import studio
import turbopush_local

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = studio.ROOT
        self.config = studio.CONFIG.copy()
        studio.ROOT = Path(self.temp.name) / 'wechat-content-studio'
        studio.ROOT.mkdir()
        for name in ('jobs', 'outbox', 'state'): (studio.ROOT/name).mkdir()
        studio.CONFIG['turbopush_enabled'] = False

    def tearDown(self):
        studio.ROOT = self.original
        studio.CONFIG.clear(); studio.CONFIG.update(self.config)
        self.temp.cleanup()

    def fixture(self, kind='video'):
        job=studio.new_job(kind,'fixture'); folder=studio.version_dir(job)
        artifact=folder/('review.mp4' if kind=='video' else 'article.html')
        artifact.write_bytes(b'fixture, not a real video')
        sources={}
        if kind=='video':
            studio.write(folder/'video-metadata.json',{'title':'真实标题','description':'完整简介。\n第二行。',
                         'account':{'id':7,'name':'目标测试账号'}})
            sources['video-metadata.json']=studio.sha(folder/'video-metadata.json')
        studio.write(folder/'manifest.json',{'sources':sources,'outputs':{artifact.name:studio.sha(artifact)},'qa':{kind:{'passed':True}}})
        studio.write(folder/'visual-review.json',{'checked':True,'notes':'fixture review'})
        return job,folder,artifact

    def confirmation(self,text,user='reviewer',msgid='confirm',group=None):
        active={'msgid':msgid,'user_id':user,'chattype':'group' if group else 'single','reply_to':group or user}
        studio.write(studio.ROOT/'state/active-wecom-task.json',active)
        inbox=studio.ROOT.parent/'wecom-bot-local/state/inbox'; inbox.mkdir(parents=True,exist_ok=True)
        studio.write(inbox/(studio.hashlib.sha256(msgid.encode()).hexdigest()+'.json'),
                     {**active,'chatid':group,'text':text,'received_at':studio.now()})
        return 'wecom:'+msgid

    def sent_video(self,job,group=None):
        self.confirmation('make a video',msgid='source',group=group)
        path=Path(studio.deliver(job['id'])['outbox'])
        studio.write(path,{**studio.read(path),'status':'sent','sent_at':'2000-01-01T00:00:00+00:00',
                          'steps':[{'step':'text','errcode':0},{'step':'file:0','errcode':0}]})
        return path

    def test_mp4_and_exact_metadata_without_phone_preview_or_remote_draft(self):
        job,folder,video=self.fixture(); item=studio.read(Path(studio.deliver(job['id'])['outbox']))
        for text in ('真实标题','完整简介。\n第二行。','目标测试账号','仅上传视频号草稿箱'):
            self.assertIn(text,item['text'])
        self.assertEqual(item['files'],[{'path':str(video),'sha256':studio.sha(video)}])
        self.assertEqual(item['video_metadata_sha256'],studio.sha(folder/'video-metadata.json'))
        self.assertNotIn('images',item)
        self.assertFalse((folder/'turbopush-remote.json').exists())

    def test_ok_requires_file_ack_and_same_conversation_and_only_authorizes_draft(self):
        job,folder,_=self.fixture()
        source=self.confirmation('OK '+job['id']+'-v1')
        with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,source)
        path=self.sent_video(job); original=studio.read(path)
        studio.write(path,{**original,'steps':[{'step':'text','errcode':0}]})
        with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,source)
        studio.write(path,original)
        source=self.confirmation('OK '+job['id']+'-v1',user='someone-else')
        with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,source)
        source=self.confirmation('OK '+job['id']+'-v1')
        result=studio.confirm_video(job['id'],1,source); approval=result['draft_request']
        self.assertTrue(approval['syncDraft']); self.assertFalse(approval['public_publish_authorized'])
        self.assertFalse(result['published']); self.assertNotIn('publish_request',result)
        self.assertEqual(approval['title'],'真实标题')
        self.assertEqual(approval['account'],{'id':7,'name':'目标测试账号'})
        self.assertEqual(approval['manifest_sha256'],studio.sha(folder/'manifest.json'))
        self.assertEqual(studio.confirm_video(job['id'],1,source)['status'],'already_confirmed')

    def test_other_group_member_can_confirm_same_group(self):
        job,_,_=self.fixture(); self.sent_video(job,group='group-1')
        source=self.confirmation('OK',user='second-member',group='group-1')
        self.assertEqual(studio.confirm_video(None,None,source)['draft_request']['reviewer'],'second-member')

    def test_plain_ok_requires_one_current_pending_video(self):
        first,_,_=self.fixture(); self.sent_video(first)
        second,_,_=self.fixture(); self.sent_video(second)
        source=self.confirmation('ok')
        with self.assertRaises(ValueError): studio.confirm_video(None,None,source)
        studio.revise(first['id'],'replace old version')
        self.assertEqual(studio.confirm_video(None,None,source)['job_id'],second['id'])
        source=self.confirmation('确认上传 '+first['id']+'-v1',msgid='old-version')
        with self.assertRaises(ValueError): studio.confirm_video(first['id'],1,source)

    def test_metadata_and_video_changes_rejected(self):
        for field in ('title','description','account','video'):
            with self.subTest(field=field):
                job,folder,video=self.fixture(); self.sent_video(job)
                source=self.confirmation('OK '+job['id']+'-v1')
                if field=='video': video.write_bytes(b'changed')
                else:
                    data=studio.read(folder/'video-metadata.json'); data[field]='changed'
                    studio.write(folder/'video-metadata.json',data)
                with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,source)

    def test_fabricated_receipt_or_confirmation_before_delivery_rejected(self):
        job,_,_=self.fixture(); path=self.sent_video(job); source=self.confirmation('OK '+job['id']+'-v1')
        with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,'wecom:fabricated')
        studio.write(path,{**studio.read(path),'sent_at':'2999-01-01T00:00:00+00:00'})
        with self.assertRaises(ValueError): studio.confirm_video(job['id'],1,source)

    def test_metadata_required(self):
        job,folder,_=self.fixture()
        for field in ('title','description','account'):
            original=studio.read(folder/'video-metadata.json')
            studio.write(folder/'video-metadata.json',{**original,field:''})
            with self.assertRaises(ValueError): studio.video_metadata(job,folder)
            studio.write(folder/'video-metadata.json',original)

    def test_article_requires_actual_official_preview(self):
        job,_,_=self.fixture('article')
        self.assertEqual(studio.deliver(job['id'])['status'],'awaiting_official_preview')
        self.assertEqual(list((studio.ROOT/'outbox').glob('*')),[])
        with self.assertRaises(ValueError): studio.review(job['id'],1,'fixture-message')
        result=studio.attach_link(job['id'],1,'https://mp.weixin.qq.com/s/fixture','fixture-message')
        self.assertIn('公众号草稿预览：https://mp.weixin.qq.com/s/fixture',studio.read(Path(result['outbox']))['text'])
        self.assertFalse(studio.review(job['id'],1,'fixture-message')['published'])

    def test_admin_local_and_foreign_urls_rejected(self):
        for url in ('http://mp.weixin.qq.com/s?x=1','http://localhost/a','https://mp.weixin.qq.com/cgi-bin/home','https://mp.weixin.qq.com.evil.test/s?x=1'):
            with self.assertRaises(ValueError): studio.official_url(url)

    def test_idempotent_delivery_and_changed_artifacts_rejected(self):
        job,_,artifact=self.fixture()
        first=studio.deliver(job['id']); second=studio.deliver(job['id'])
        self.assertEqual(first['outbox'],second['outbox'])
        self.assertEqual(len(list((studio.ROOT/'outbox').glob('*'))),1)
        artifact.write_bytes(b'changed')
        with self.assertRaises(ValueError): studio.deliver(job['id'])

    def test_failed_qa_rejected(self):
        job,folder,_=self.fixture(); manifest=studio.read(folder/'manifest.json')
        manifest['qa']['video']['passed']=False; studio.write(folder/'manifest.json',manifest)
        with self.assertRaises(ValueError): studio.deliver(job['id'])

    def test_switch_destination_keeps_video_attachment(self):
        job,_,_=self.fixture()
        studio.CONFIG['review_destination']={'provider':'desktop_wechat','group':'legacy'}
        first=studio.deliver(job['id'])
        studio.CONFIG['review_destination']={'provider':'wecom','chatid':'new-group'}
        second=studio.deliver(job['id'])
        self.assertNotEqual(first['outbox'],second['outbox'])
        self.assertEqual(len(studio.read(Path(second['outbox']))['files']),1)

    def test_revision_copies_metadata_but_not_approval_or_video(self):
        job,folder,_=self.fixture(); self.sent_video(job)
        studio.confirm_video(job['id'],1,self.confirmation('OK '+job['id']+'-v1'))
        revised=studio.revise(job['id'],'shorten opening'); next_folder=studio.version_dir(revised)
        self.assertTrue((folder/'video-draft-approval.json').exists())
        self.assertEqual(studio.read(next_folder/'video-metadata.json'),studio.read(folder/'video-metadata.json'))
        self.assertFalse((next_folder/'video-draft-approval.json').exists())
        self.assertFalse((next_folder/'review.mp4').exists())

    def test_local_import_keeps_reviewed_title_description_and_draft_flag(self):
        job,folder,video=self.fixture(); calls=[]; stored={}
        def request(endpoint,body=None):
            calls.append(endpoint)
            if endpoint=='/article/video': stored.update(body); return {'id':12}
            if endpoint=='/article/get/12': return {'status':1,'publish_data':stored}
            self.fail('Unexpected endpoint: '+endpoint)
        with patch.object(turbopush_local,'request_local',side_effect=request):
            receipt=turbopush_local.import_video(job['id']); turbopush_local.import_video(job['id'])
        self.assertEqual(stored['title'],'真实标题'); self.assertEqual(stored['desc'],'完整简介。\n第二行。')
        self.assertTrue(stored['syncDraft']); self.assertEqual(stored['files'],[str(video)])
        self.assertFalse(receipt['video_channel_uploaded']); self.assertEqual(calls.count('/article/video'),1)

if __name__=='__main__': unittest.main()
