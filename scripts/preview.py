#!/usr/bin/env python3
"""Loopback-only seeded preview; never installs services or starts sing-box."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import secrets
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app import Store, Handler, ThreadingHTTPServer, password_hash
from model import initial,credential

os.umask(0o077)
root=Path(__file__).resolve().parents[1]
settings={'data':str(root/'.local/preview'),'preview':True,'production':False,'host':'node.example.com','tls_name':'www.bing.com','self_signed':True,'public_url':'http://127.0.0.1:18093/freedom-network','base_path':'/freedom-network','web_port':18898,'api_port':18093,'stats_port':18091,'cert':'/tmp/unused-preview-cert','key':'/tmp/unused-preview-key','reality_private':'preview-only','reality_public':'preview-only','reality_sni':'apple.com','short_id':'abcd','vmess_tls':False,'vmess_ws_path':'preview-entry-vm'}
store=Store(settings)
if not store.db.execute('SELECT 1 FROM state').fetchone():
    state=initial();expiry=(dt.date.today()+dt.timedelta(days=30)).isoformat()
    for index,(name,quota) in enumerate([('Alex Chen',200),('林小雨',100),('Design Studio',500),('测试账户',10)]):
        state['users'].append({'id':'preview'+str(index),'name':name,'active':index!=3,'quota':quota,'expire':expiry,'token':secrets.token_urlsafe(32),'credentials':{n:credential(n) for n in (['TUIC v5'] if index==1 else ['VMess','TUIC v5'])}})
    with store.db:
        store.db.execute('INSERT INTO state VALUES(1,?)',(json.dumps(state),))
        store.db.execute('INSERT INTO admin VALUES(1,?,?)',('preview',password_hash('local-preview-2026')))
        now=int(time.time())
        for i in range(24):
            for j,u in enumerate(state['users'][:3]):
                upload=int((18+12*math.sin(i/3+j)**2+j*5)*1024**2)
                download=int(upload*(2.3+.9*math.cos(i/4)**2))
                ts=now-(23-i)*3600
                for direction,value in [('uplink',upload),('downlink',download)]:store.db.execute('INSERT INTO traffic VALUES(?,?,?,?,?)',(ts,u['id'],'tuic',direction,value))

def simulate():
    tick=0
    while True:
        with store.lock,store.db:
            tick+=1;now=int(time.time())
            for i,u in enumerate(store.load()['users']):
                if not u['active']:continue
                protocol='tuic' if 'TUIC v5' in u['credentials'] else 'vmess'
                for direction,amount in [('uplink',(i+1)*32768*(1+tick%4)),('downlink',(i+1)*196608*(1+tick%5))]:store.db.execute('INSERT INTO traffic VALUES(?,?,?,?,?)',(now,u['id'],protocol,direction,amount))
            store.stats_status='模拟流量 · 本地预览，不连接真实代理';store.last_sample=now
        time.sleep(10)
threading.Thread(target=simulate,daemon=True).start()
store.monitor.start()
class PreviewHandler(Handler):
    # This handler exists only in the loopback simulation, never in app.py serve.
    def session(self): return ('local-preview','local-preview-csrf')

server=ThreadingHTTPServer(('127.0.0.1',18093),PreviewHandler);server.store=store;server.attempts=[]
print('预览地址：http://127.0.0.1:18093/freedom-network/\n仅本地测试账号：preview / local-preview-2026\n统计由模拟数据每10秒更新，页面每5秒读取。',flush=True)
server.serve_forever()
