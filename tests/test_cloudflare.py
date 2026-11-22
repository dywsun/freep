import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_backend import CoreTests
from cloudflare import https_url,public_ip

class GatewayTests(unittest.TestCase):
    setUp=CoreTests.setUp
    create=CoreTests.create
    def register(self):
        gateway=self.store.cloudflare
        with patch('cloudflare.request',return_value={'ok':True,'id':gateway.config['id']}) as call,patch.object(gateway,'start'):
            gateway.register({'url':'https://gateway.example.com','token':'registration-secret-token-123456','ip':'8.8.8.8','origin':'https://origin.example.com/freedom/sub','name':'Example'})
        return gateway,call
    def test_register_and_mode_switch(self):
        user=self.create();gateway,call=self.register()
        self.assertEqual(gateway.config['mode'],'local')
        self.assertTrue(self.store.public_state()['users'][0]['subscription'].startswith(self.settings['public_url']))
        gateway.configure({'mode':'worker'})
        self.assertEqual(self.store.public_state()['users'][0]['subscription'],'https://gateway.example.com/sub/'+gateway.config['id']+'/'+user['token'])
        self.assertNotIn('registration-secret',gateway.path.read_text())
        self.assertEqual(os.stat(gateway.path).st_mode&0o777,0o600)
        self.assertNotIn(gateway.config['key'],json.dumps(gateway.public()))
        args=call.call_args.args
        self.assertEqual(args[0],'https://gateway.example.com/api/register')
        payload=json.loads(args[2]);self.assertEqual(payload['id'],gateway.config['id']);self.assertEqual(payload['ip'],'8.8.8.8')
        gateway.configure({'mode':'local'})
        self.assertTrue(gateway.subscription_base().startswith(self.settings['public_url']))
    def test_update_uses_independent_key_no_user_snapshots(self):
        self.create();gateway,_=self.register()
        with patch('cloudflare.request',return_value={'ok':True,'enabled':False}) as call:
            gateway.sync({'ip':'1.1.1.1'})
        self.assertEqual(call.call_args.args[0],'https://gateway.example.com/api/node/update')
        self.assertEqual(json.loads(call.call_args.args[2]),{'id':gateway.config['id'],'ip':'1.1.1.1'})
        self.assertEqual(call.call_args.args[3]['Authorization'],'Bearer '+gateway.config['key'])
        self.assertEqual(gateway.config['ip'],'1.1.1.1')
    def test_validation_and_unregistered_mode(self):
        for value in ['http://gateway.example.com','https://127.0.0.1','https://gateway.example.com:18898','https://user:pass@gateway.example.com','https://gateway.example.com/other']:
            with self.assertRaises(ValueError):https_url(value,True)
        for value in ['127.0.0.1','10.0.0.1','::1']:
            with self.assertRaises(ValueError):public_ip(value)
        with self.assertRaises(ValueError):self.store.cloudflare.configure({'mode':'worker'})
        self.settings['preview']=True
        with self.assertRaises(ValueError):self.store.cloudflare.register({})
    def test_failed_register_preserves_existing_binding(self):
        gateway,_=self.register();before=gateway.config.copy()
        with patch('cloudflare.request',side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):gateway.register({'url':'https://other.example.com','ip':'8.8.8.8','origin':'https://origin.example.com/sub','token':'a'*32})
        self.assertEqual(gateway.config,before)
