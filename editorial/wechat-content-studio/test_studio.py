import json
import tempfile
import unittest
from pathlib import Path
import studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = studio.ROOT
        studio.ROOT = Path(self.temp.name)
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
        return job,folder,artifact

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
