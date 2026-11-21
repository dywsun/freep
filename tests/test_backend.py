import base64
import copy
import datetime
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import Store, Handler, ThreadingHTTPServer, password_hash, check_password
from model import initial, credential, server_config, subscription, validate

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.settings={'data':self.tmp.name,'host':'node.example.com','public_url':'http://127.0.0.1:9999','web_port':18898,'api_port':18090,'stats_port':18091,'cert':'/tmp/cert.pem','key':'/tmp/key.pem','tls_name':'node.example.com','self_signed':True,'reality_private':'test','reality_public':'test','reality_sni':'www.apple.com','short_id':'abcd'}
        self.applied=[];self.store=Store(self.settings,apply=lambda s:self.applied.append(copy.deepcopy(s)))
        self.addCleanup(self.store.db.close)
        with self.store.db:
            self.store.db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(initial()),))
            self.store.db.execute('INSERT INTO admin VALUES(1,?,?)',('admin',password_hash('test-password-123')))
    def create(self):
        s=self.store.load()
        return self.store.mutate('user-create',{'revision':s['revision'],'name':'Alice','quota':100,'expire':'2099-12-31','protocols':['VMess','TUIC v5']})['users'][-1]
    def test_shared_ports_independent_credentials(self):
        a=self.create();b=self.create();s=self.store.load();c=server_config(s,self.settings)
        self.assertEqual(len(c['inbounds']),2)
        self.assertEqual([len(x['users']) for x in c['inbounds']],[2,2])
        self.assertNotEqual(a['credentials']['VMess']['uuid'],b['credentials']['VMess']['uuid'])
        self.assertNotEqual(a['credentials']['VMess']['uuid'],a['credentials']['TUIC v5']['uuid'])
        self.assertEqual(c['inbounds'][0]['listen_port'],8880)
        self.assertEqual(len(c['experimental']['v2ray_api']['stats']['users']),4)
    def test_failed_apply_does_not_commit(self):
        self.store.apply_callback=lambda s:(_ for _ in ()).throw(ValueError('failed'))
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.store.load()['users'],[])
        self.assertEqual(self.store.load()['revision'],0)
    def test_revision_and_reserved_port(self):
        self.create()
        with self.assertRaises(ValueError):self.store.mutate('protocol-update',{'revision':0,'name':'VMess','port':20000})
        with self.assertRaises(AssertionError):self.store.mutate('protocol-update',{'revision':1,'name':'VMess','port':18090})
    def test_revoke_and_rotation(self):
        a=self.create();self.create()
        s=self.store.mutate('user-reset',{'revision':2,'id':a['id'],'protocol':'VMess'})
        self.assertNotEqual(s['users'][0]['credentials']['VMess'],a['credentials']['VMess'])
        self.assertEqual(s['users'][0]['credentials']['TUIC v5'],a['credentials']['TUIC v5'])
        s=self.store.mutate('user-update',{'revision':3,'id':a['id'],'active':False})
        self.assertEqual(len(server_config(s,self.settings)['inbounds'][0]['users']),1)
        content,_=subscription(s,s['users'][0],self.settings,'uri')
        self.assertEqual(base64.b64decode(content),b'')
    def test_expired_or_quota_users_excluded(self):
        a=self.create();s=self.store.load();s['users'][0]['expire']='2000-01-01'
        self.assertEqual(server_config(s,self.settings)['inbounds'],[])
        s['users'][0]['expire']='2099-12-31'
        self.assertEqual(server_config(s,self.settings,{a['id']:100*1024**3})['inbounds'],[])
    def test_stats_idempotence_restart_and_persistence(self):
        a=self.create();name=f'user>>>{a["id"]}:tuic>>>traffic>>>uplink'
        for value,epoch in [(100,'a'),(100,'a'),(150,'a'),(20,'b'),(30,'b')]:self.store.record({name:value},epoch)
        self.assertEqual(self.store.totals()[a['id']],180)
        other=Store(self.settings);self.assertEqual(other.totals()[a['id']],180);other.db.close()
    def test_subscription_isolation(self):
        a=self.create();b=self.create();s=self.store.load()
        for fmt in ['uri','karing','singbox','mihomo']:
            content,_=subscription(s,a,self.settings,fmt)
            decoded=base64.b64decode(content).decode() if fmt in ('uri','karing') else content.decode()
            if fmt in ('uri','karing'):
                vmess=next(l for l in decoded.splitlines() if l.startswith('vmess://'))
                decoded+=base64.b64decode(vmess[8:]).decode()
            self.assertIn(a['credentials']['VMess']['uuid'],decoded)
            self.assertNotIn(b['credentials']['VMess']['uuid'],decoded)
            self.assertIn('32786',decoded)
    def test_original_defaults_and_overrides(self):
        self.create();s=self.store.load();cfg=server_config(s,self.settings)
        vmess=next(i for i in cfg['inbounds'] if i['type']=='vmess')
        self.assertNotIn('tls',vmess)
        self.assertEqual(vmess['transport']['max_early_data'],2048)
        settings={**self.settings,'vmess_tls':True,'vmess_ws_path':'shared-id-vm','tuic_congestion_control':'cubic'}
        cfg=server_config(s,settings)
        self.assertTrue(cfg['inbounds'][0]['tls']['enabled'])
        self.assertEqual(cfg['inbounds'][0]['transport']['path'],'shared-id-vm')
        self.assertEqual(cfg['inbounds'][1]['congestion_control'],'cubic')
        nodes=json.loads(subscription(s,s['users'][0],settings,'singbox')[0])['outbounds']
        self.assertEqual(next(n for n in nodes if n['type']=='vmess')['transport']['path'],'shared-id-vm')

    def test_auth_hash(self):
        encoded=password_hash('another-password-456')
        self.assertTrue(check_password('another-password-456',encoded));self.assertFalse(check_password('wrong-password-456',encoded))
        self.assertNotIn('another-password',encoded)

class HttpTests(CoreTests):
    def test_http_auth_csrf_and_subscription(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.store=self.store;server.attempts=[]
        self.settings['public_url']=f'http://127.0.0.1:{server.server_port}'
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        self.addCleanup(conn.close)
        def req(method,path,payload=None,headers=None):
            h={'Origin':self.settings['public_url'],'Content-Type':'application/json',**(headers or {})}
            conn.request(method,path,json.dumps(payload) if payload is not None else None,h)
            r=conn.getresponse();body=r.read();return r,body
        r,_=req('GET','/api/state');self.assertEqual(r.status,401)
        r,_=req('GET','/api/share?id=unknown');self.assertEqual(r.status,401)
        r,_=req('POST','/api/login',{'username':'admin','password':'bad-password-123'});self.assertEqual(r.status,401)
        r,body=req('POST','/api/login',{'username':'admin','password':'test-password-123'})
        self.assertEqual(r.status,200);cookie=r.getheader('Set-Cookie').split(';')[0];csrf=json.loads(body)['csrf']
        headers={'Cookie':cookie}
        r,_=req('POST','/api/action',{'action':'user-create'},headers);self.assertEqual(r.status,403)
        headers['X-CSRF-Token']=csrf
        r,body=req('POST','/api/action',{'action':'user-create','revision':0,'name':'HTTP test','quota':100,'expire':'2099-12-31','protocols':['VMess','TUIC v5']},headers)
        self.assertEqual(r.status,200,body);u=json.loads(body)['users'][0]
        r,body=req('GET','/sub/'+u['token']+'?format=singbox');self.assertEqual(r.status,200,body);self.assertIn(u['credentials']['VMess']['uuid'],body.decode())
        r,body=req('GET','/api/share?id='+u['id'],headers=headers)
        self.assertEqual(r.status,200,body);nodes=json.loads(body)['nodes']
        self.assertEqual({n['protocol'] for n in nodes},{'VMess','TUIC v5'})
        vmess=next(n['uri'] for n in nodes if n['protocol']=='VMess')
        self.assertEqual(json.loads(base64.b64decode(vmess[8:]))['id'],u['credentials']['VMess']['uuid'])
        self.assertIn(u['credentials']['TUIC v5']['uuid'],next(n['uri'] for n in nodes if n['protocol']=='TUIC v5'))
        r,_=req('GET','/api/share?id=unknown',headers=headers);self.assertEqual(r.status,404)
        r,_=req('GET','/sub/not-a-token');self.assertEqual(r.status,404)
        r,_=req('POST','/api/logout',{},headers);self.assertEqual(r.status,200)
        r,_=req('GET','/api/state',headers=headers);self.assertEqual(r.status,401)

class PrefixTests(CoreTests):
    def test_prefixed_login_assets_subscriptions_and_cookie(self):
        prefix='/freedom-network'
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.store=self.store;server.attempts=[]
        origin=f'http://127.0.0.1:{server.server_port}'
        self.settings.update(base_path=prefix,public_url=origin+prefix)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port);self.addCleanup(conn.close)
        def request(method,path,payload=None,headers=None):
            conn.request(method,path,json.dumps(payload) if payload is not None else None,{'Content-Type':'application/json','Origin':origin,**(headers or {})})
            r=conn.getresponse();return r,r.read()
        for path in ('/','/api/health','/api/login','/app.js','/freedom-network-other/'):
            r,_=request('GET',path);self.assertEqual(r.status,404,path)
        r,_=request('GET',prefix);self.assertEqual(r.status,308);self.assertEqual(r.getheader('Location'),prefix+'/')
        r,body=request('GET',prefix+'/');self.assertEqual(r.status,200);self.assertIn(b'window.RELAY_BASE_PATH="/freedom-network"',body)
        for asset in ['app.js','live.js','style.css','share.js','vendor/qrcode.js']:
            r,_=request('GET',prefix+'/'+asset);self.assertEqual(r.status,200)
        r,body=request('POST',prefix+'/api/login',{'username':'admin','password':'test-password-123'})
        self.assertEqual(r.status,200,body);self.assertIn('Path=/freedom-network/;',r.getheader('Set-Cookie'))
        csrf=json.loads(body)['csrf'];cookie=r.getheader('Set-Cookie').split(';')[0]
        headers={'Cookie':cookie,'X-CSRF-Token':csrf}
        r,body=request('POST',prefix+'/api/action',{'action':'user-create','revision':0,'name':'Prefix user','quota':10,'expire':'2099-12-31','protocols':['VMess']},headers)
        self.assertEqual(r.status,200,body);u=json.loads(body)['users'][0]
        self.assertTrue(u['subscription'].startswith(origin+prefix+'/sub/'))
        r,_=request('GET',prefix+'/sub/'+u['token']+'?format=uri');self.assertEqual(r.status,200)
        r,_=request('GET','/sub/'+u['token']+'?format=uri');self.assertEqual(r.status,404)
        r,body=request('GET',prefix+'/api/share?id='+u['id'],headers=headers)
        self.assertEqual(r.status,200,body);self.assertEqual(len(json.loads(body)['nodes']),1)
        r,_=request('GET','/api/share?id='+u['id'],headers=headers);self.assertEqual(r.status,404)
        state=self.store.load()
        self.store.mutate('user-update',{'revision':state['revision'],'id':u['id'],'active':False})
        r,_=request('GET',prefix+'/api/share?id='+u['id'],headers=headers);self.assertEqual(r.status,400)

        r,_=request('POST',prefix+'/api/logout',{},headers);self.assertEqual(r.status,200);self.assertIn('Path=/freedom-network/;',r.getheader('Set-Cookie'))

if __name__=='__main__':unittest.main()
