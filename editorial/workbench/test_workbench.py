import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server import Workbench, Server, Conflict


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.studio, self.bot, self.state = (self.root/name for name in ('studio', 'bot', 'workbench'))
        self.app = Workbench(self.studio, self.bot, self.state)
        self.folder = self.studio/'jobs/C0001/v1'
        write(self.folder.parent/'job.json', {'id':'C0001','version':1,'kind':'both','status':'awaiting_review','topic':'人物纪录片','updated_at':'2026-10-23T00:00:00Z'})
        write(self.folder/'article.json', {'title':'真实内容','sections':[],'sources':[]})
        write(self.folder/'video-metadata.json', {'title':'真实视频名','description':'完整简介','account':{'id':1,'name':'示例账号','secret':'do-not-expose'}})
        write(self.folder/'manifest.json', {'qa':{'video':{'passed':True,'duration_seconds':12},'article':{'passed':True}}})
        write(self.folder/'official-preview.json', {'url':'https://mp.weixin.qq.com/s?tempkey=example'})
        write(self.folder/'official/receipt.json', {'state':'preview_available','access_token':'do-not-expose'})
        write(self.folder/'turbopush-remote.json', {'record_success':True,'syncDraft':True,'record_id':7,'detail':{'cookie':'do-not-expose'}})
        write(self.bot/'state/connectivity.json', {'authenticated':True,'socket_connected':True,'last_health_at':datetime.now(timezone.utc).isoformat(),'bot_secret':'do-not-expose'})
        (self.folder/'review.mp4').write_bytes(b'0123456789')

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **extra):
        return {'topic':'下期选题','kind':'both','channel':'both','owner':'编辑','date':'2026-10-24','notes':'人物风格','job_id':'C0001','revision':0,**extra}


class WorkbenchTests(Fixture):
    def test_snapshot_reports_real_receipts_without_raw_secrets_or_chat(self):
        write(self.bot/'state/inbox/fixture.json', {'status':'outcome_unknown','text':'private conversation','user_id':'private-user'})
        data = self.app.snapshot()
        raw = json.dumps(data)
        for private in ('do-not-expose','private conversation','private-user'):
            self.assertNotIn(private, raw)
        self.assertEqual(data['stats']['total'], 1)
        self.assertEqual(data['stats']['review'], 1)
        self.assertTrue(data['tasks'][0]['current']['video_draft_uploaded'])
        self.assertEqual(data['integrations'][0]['status'], 'online')
        self.assertEqual(data['queues']['incoming']['counts']['outcome_unknown'], 1)

    def test_stale_heartbeat_never_appears_online(self):
        write(self.bot/'state/connectivity.json', {'authenticated':True,'socket_connected':True,
              'last_health_at':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()})
        self.assertEqual(self.app.integrations()[0]['status'], 'stale')

    def test_mcp_configuration_is_read_from_the_studio_without_claiming_online(self):
        write(self.studio/'state/turbopush-mcp.json', {'enabled':True,'command':'private-path','sha256':'private-hash'})
        row = self.app.integrations()[-1]
        self.assertEqual(row['status'], 'configured')
        self.assertIn('在线待确认', row['label'])
        self.assertNotIn('private-', json.dumps(row))

    def test_public_post_or_local_acceptance_is_not_draft_upload_success(self):
        for remote in ({'record_success':True,'syncDraft':False}, {'status':'accepted','syncDraft':True}):
            write(self.folder/'turbopush-remote.json', remote)
            self.assertFalse(self.app.version_summary('C0001',1)['video_draft_uploaded'])

    def test_version_history_and_external_url_validation(self):
        write(self.studio/'jobs/C0001/v2/article.json', {'title':'第二版'})
        write(self.folder/'official-preview.json', {'url':'javascript:alert(1)'})
        detail = self.app.detail('C0001')
        self.assertEqual([v['version'] for v in detail['versions']], [2,1])
        self.assertIsNone(detail['versions'][1]['official_preview'])

    def test_plan_is_persisted_separately_without_altering_production_files(self):
        original = (self.folder.parent/'job.json').read_bytes()
        result = self.app.save_plan(self.plan())
        self.assertEqual(self.app.plans(), result)
        self.assertEqual(result['items'][0]['job_id'], 'C0001')
        self.assertEqual((self.folder.parent/'job.json').read_bytes(), original)
        self.assertFalse((self.studio/'outbox').exists())
        self.assertFalse((self.folder/'review.json').exists())
        self.assertFalse((self.folder/'video-draft-approval.json').exists())

    def test_conflicting_save_and_invalid_dates_are_rejected(self):
        self.app.save_plan(self.plan())
        with self.assertRaises(Conflict):
            self.app.save_plan(self.plan())
        with self.assertRaises(ValueError):
            self.app.save_plan(self.plan(revision=1,date='2026-99-99'))
        with self.assertRaises(ValueError):
            self.app.save_plan(self.plan(revision=1,job_id='C9999'))

    def test_corrupt_plans_cannot_be_silently_overwritten(self):
        self.state.mkdir();(self.state/'plans.json').write_text('{broken',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'数据损坏'):
            self.app.save_plan(self.plan())
        self.assertEqual((self.state/'plans.json').read_text(), '{broken')

    def test_missing_and_malformed_jobs_are_reported_honestly(self):
        write(self.studio/'jobs/C0002/job.json', {'id':'different'})
        data = self.app.snapshot()
        self.assertEqual(data['data_issues'], ['C0002'])
        empty = Workbench(self.root/'missing', self.bot, self.state).snapshot()
        self.assertEqual(empty['stats']['total'], 0)
        self.assertFalse(empty['studio_exists'])


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = Server(0, self.app)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.worker.join()
        super().tearDown()

    def request(self, path, method='GET', body=None, headers=None, authenticated=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        request_headers = {'Cookie':'editorial_session='+self.server.session} if authenticated else {}
        request_headers.update(headers or {})
        connection.request(method, path, body, request_headers)
        response = connection.getresponse();result = (response.status,dict(response.getheaders()),response.read())
        connection.close();return result

    def test_local_page_cookie_auth_and_cross_origin_guards(self):
        status, headers, _ = self.request('/', authenticated=False)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/snapshot',authenticated=False)[0],403)
        self.assertEqual(self.request('/api/snapshot',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/snapshot',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/snapshot')[0],200)

    def test_media_range_head_and_traversal_controls(self):
        path='/media/C0001/v1/review.mp4'
        status,headers,raw = self.request(path,headers={'Range':'bytes=2-5'})
        self.assertEqual((status,raw),(206,b'2345'))
        self.assertEqual(headers['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.request(path,headers={'Range':'bytes=-3'})[2],b'789')
        self.assertEqual(self.request(path,headers={'Range':'bytes=200-300'})[0],416)
        self.assertEqual(self.request(path,method='HEAD')[2],b'')
        self.assertEqual(self.request('/media/C0001/v1/%2e%2e%2fconfig.json')[0],404)
        self.assertEqual(self.request('/media/C0001/v1/manifest.json')[0],404)

    def test_symlink_escape_is_not_exposed(self):
        outside = self.root/'private.mp4';outside.write_bytes(b'private')
        (self.folder/'review.mp4').unlink()
        try:
            (self.folder/'review.mp4').symlink_to(outside)
        except OSError:
            self.skipTest('Creating symlinks is unavailable on this host')
        self.assertEqual(self.request('/media/C0001/v1/review.mp4')[0],404)

    def test_plan_write_needs_same_origin_and_preserves_conflicts(self):
        body=json.dumps(self.plan())
        self.assertEqual(self.request('/api/plans','POST',body,{'Content-Type':'application/json'})[0],403)
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{self.port}'}
        self.assertEqual(self.request('/api/plans','POST',body,headers)[0],200)
        self.assertEqual(self.request('/api/plans','POST',body,headers)[0],409)
        self.assertEqual(self.request('/api/publish','POST','{}',headers)[0],404)


if __name__ == '__main__':
    unittest.main()
