import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock

spec=importlib.util.spec_from_file_location('wxinventory',Path(__file__).with_name('inspect-wxcloud.py'))
inventory=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        (root/'appid').write_text('wx0000000000000000',encoding='utf-8')
        (root/'key').write_text('unit-test-private-value',encoding='utf-8')
        self.client=inventory.Client(root/'appid',root/'key')

    def tearDown(self):
        self.tmp.cleanup()

    def test_mutating_cloud_actions_are_rejected_before_any_request(self):
        self.client.request=Mock()
        for action in ('SubmitServerRelease','EstablishCloudBaseRunServerWx','DeleteCloudBaseRunServer'):
            with self.assertRaises(ValueError):self.client.action(action,{})
        self.client.request.assert_not_called()

    def test_inventory_does_not_return_unselected_cloud_fields(self):
        self.client.request=Mock(return_value={})
        self.client.action=Mock(side_effect=[
            {'EnvList':[{'EnvId':'env-fixture','Alias':'test','Region':'ap-shanghai','secret':'unit-test-private-value'}]},
            {'CloudBaseRunServerSet':[{'ServerName':'fixture','EnvParams':'private credentials'}]},
            {'DefaultPublicDomain':'https://fixture.example','AccessTypes':['PUBLIC'],'token':'private token'},
            {'DbClusterId':'db-fixture','DbInfo':{'Status':'running','IsOpenPubNetAccess':False},'password':'private credentials'}])
        result=inventory.inspect(self.client)
        raw=json.dumps(result)
        for value in ('unit-test-private-value','private credentials','private token'):
            self.assertNotIn(value,raw)
        self.assertFalse(result['cloud_resources_changed'])
        self.assertTrue(result['credentials_accepted'])

    def test_failed_authorization_reports_code_without_echoing_response(self):
        self.client.opener=MagicMock()
        self.client.opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(
            {'base_resp':{'ret':-1,'errmsg':'unit-test-private-value'}}).encode()
        with self.assertRaises(RuntimeError) as caught:self.client.request('getqbaseinfo',{})
        self.assertNotIn('unit-test-private-value',str(caught.exception))
        self.assertIn('-1',str(caught.exception))


if __name__=='__main__':unittest.main()
