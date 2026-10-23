"""Failure-boundary tests for durability, public access, and source transport."""
import base64
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from cloud import client, store


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class CloudTests(unittest.TestCase):
    def test_model_provider_requires_explicit_secure_configuration_and_keeps_key_out_of_toml(self):
        from cloud.model_config import validate,provider_toml
        import tomllib
        value={'base_url':'https://model.example/v1','model':'fixture-model','api_key':'private-test-key'}
        self.assertEqual(validate(value),value)
        text=provider_toml(value['base_url'],value['model']);parsed=tomllib.loads(text)
        self.assertNotIn(value['api_key'],text)
        self.assertEqual(parsed['model_providers']['cloud_model']['env_key'],'EDITORIAL_MODEL_API_KEY')
        self.assertFalse(parsed['model_providers']['cloud_model']['requires_openai_auth'])
        for url in ('http://model.example/v1','https://user:password@model.example/v1','https://model.example/v1?key=bad'):
            with self.assertRaises(ValueError):validate({**value,'base_url':url})

    def test_failed_database_commit_does_not_update_local_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'editorial/wecom-bot-local/state/inbox/one.json'
            path.parent.mkdir(parents=True);path.write_text('{"status":"queued"}')
            value=object.__new__(store.Store);value.guard=threading.RLock()
            value.upsert=Mock(side_effect=RuntimeError('database unavailable'))
            with patch.object(store,'ROOT',root),patch('cloud.store.safe_path',lambda p: (Path(p),'editorial/wecom-bot-local/state/inbox/one.json')):
                with self.assertRaises(RuntimeError):value.write(path,{'status':'running'})
            self.assertEqual(json.loads(path.read_text())['status'],'queued')

    def test_missing_durability_service_fails_closed(self):
        with patch.dict(os.environ,{'EDITORIAL_CLOUD':'1','EDITORIAL_LOCAL_TOKEN':'local-only'}),patch(
                'urllib.request.urlopen',side_effect=OSError('network failure with private data')):
            with self.assertRaisesRegex(RuntimeError,'Cloud persistence unavailable') as error:
                client.persist('/app/editorial/wecom-bot-local/state/message.json',{'status':'queued'})
            self.assertNotIn('private data',str(error.exception))

    def test_path_traversal_credentials_and_locks_are_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('../secret','.env','cloud/state/auth.json','editorial/wecom-bot-local/state/listener.lock'):
                with self.assertRaises(ValueError):store.safe_path(name,root)
            _,key=store.safe_path('editorial/wecom-bot-local/state/inbox/one.json',root)
            self.assertTrue(key.endswith('/inbox/one.json'))

    def test_advisory_lock_is_checked_without_reconnection(self):
        value=object.__new__(store.Store);value.guard=threading.RLock();value.namespace='new-bot'
        cursor=Mock();cursor.fetchone.return_value=(0,)
        value.lease=Mock();value.lease.cursor.return_value.__enter__=Mock(return_value=cursor)
        value.lease.cursor.return_value.__exit__=Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError,'lease lost'):value.fence()
        value.lease.ping.assert_not_called()

    def test_public_cloud_requires_password_and_rejects_cross_origin(self):
        web=module('cloud_test_web',store.ROOT/'editorial/workbench/server.py')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
                'EDITORIAL_CLOUD':'1','EDITORIAL_ADMIN_PASSWORD':'test-only-long-password',
                'EDITORIAL_PUBLIC_ORIGIN':'https://editorial.example.test'}):
            app=web.Server(0,web.Workbench(folder,folder,folder))
            thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
            try:
                target=f'http://127.0.0.1:{app.server_port}'
                request=urllib.request.Request(target+'/',headers={'Host':'editorial.example.test'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,401)
                self.assertIsNone(error.exception.headers.get('Set-Cookie'))
                token=base64.b64encode(b'admin:test-only-long-password').decode()
                request.add_header('Authorization','Basic '+token)
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status,200)
                    self.assertIn('Secure',response.headers['Set-Cookie'])
                request.add_header('Origin','https://attacker.example.test')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,403)
            finally:app.shutdown();app.server_close();thread.join()

    def test_build_archive_preserves_unicode_resources_without_unicode_entries(self):
        deploy=module('cloud_test_deploy',store.ROOT/'scripts/deploy-wxcloud.py')
        raw=deploy.package([])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertTrue(all(name.isascii() for name in archive.namelist()))
            self.assertNotIn('.env',archive.namelist())
            resources=json.loads(archive.read('cloud/unicode-sources.json'))
            self.assertGreater(len(resources),0)
            for name,value in resources.items():
                self.assertEqual(base64.b64decode(value),(store.ROOT/name).read_bytes())


if __name__=='__main__':unittest.main()
