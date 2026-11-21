#!/usr/bin/env python3
"""Generate and validate every protocol with an actual sing-box binary."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from model import initial, credential, server_config, subscription

binary=os.environ['SING_BOX_BIN']
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-keyout',str(p/'key.pem'),'-out',str(p/'cert.pem')],check=True,capture_output=True)
    keys=dict(re.findall(r'(PrivateKey|PublicKey):\s*(\S+)',subprocess.check_output([binary,'generate','reality-keypair'],text=True)))
    settings={'host':'localhost','tls_name':'localhost','self_signed':True,'web_port':18898,'api_port':18090,'stats_port':18091,'cert':str(p/'cert.pem'),'key':str(p/'key.pem'),'reality_private':keys['PrivateKey'],'reality_public':keys['PublicKey'],'reality_sni':'www.apple.com','short_id':'abcdef12'}
    s=initial()
    for proto in s['protocols']:proto['active']=True
    u={'id':'test','name':'test','active':True,'token':'a'*43,'quota':100,'expire':'2099-12-31','credentials':{n['name']:credential(n['name']) for n in s['protocols']}}
    s['users']=[u]
    config=server_config(s,settings)
    if 'with_v2ray_api' not in subprocess.check_output([binary,'version'],text=True):
        print('WARNING: binary has no stats API; validating protocol fields without stats')
        config.pop('experimental')
    (p/'server.json').write_text(json.dumps(config))
    subprocess.run([binary,'check','-c',str(p/'server.json')],check=True)
    for proto in s['protocols']:
        isolated=json.loads(json.dumps(config));isolated['inbounds']=[i for i in config['inbounds'] if i['tag']=={'VMess':'vmess','TUIC v5':'tuic','VLESS':'vless','Hysteria2':'hysteria2','AnyTLS':'anytls'}[proto['name']]]
        (p/'single.json').write_text(json.dumps(isolated));subprocess.run([binary,'check','-c',str(p/'single.json')],check=True)
    client,_=subscription(s,u,settings,'singbox');(p/'client.json').write_bytes(client)
    subprocess.run([binary,'check','-c',str(p/'client.json')],check=True)
    settings['vmess_tls']=True
    tls_config=server_config(s,settings)
    if 'with_v2ray_api' not in subprocess.check_output([binary,'version'],text=True):tls_config.pop('experimental',None)
    (p/'server-tls.json').write_text(json.dumps(tls_config));subprocess.run([binary,'check','-c',str(p/'server-tls.json')],check=True)
    print('All five server protocols and sing-box client configuration passed.')
