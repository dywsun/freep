#!/usr/bin/env python3
"""Relay control plane. No shell interpolation; HTTP service runs unprivileged."""
import argparse
import base64
import copy
import datetime as dt
import hashlib
import hmac
import http.cookies
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from assets import ASSETS, API_VERSION, current_frontend, frontend_asset
from monitor import SystemMonitor
from model import KINDS, credential, eligible, initial, subscription, subscription_limits, validate

ROOT = Path(__file__).resolve().parent.parent

def password_hash(password, salt=None):
    if len(password) < 12 or len(password) > 256: raise ValueError('密码长度必须为 12–256 个字符')
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()

def check_password(password, encoded):
    try: return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)
    except (ValueError, TypeError): return False

def atomic(path, value, mode=0o600):
    path = Path(path); tmp = path.with_suffix('.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), mode)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

class Store:
    def __init__(self, settings, apply=None):
        self.settings = settings; self.directory = Path(settings['data']); self.directory.mkdir(parents=True, exist_ok=True)
        self.monitor = SystemMonitor()
        self.lock = threading.RLock(); self.apply_callback = apply; self.stats_status = '尚未采集' if settings.get('production') else '开发模式：未连接统计内核'; self.last_sample = None
        self.db = sqlite3.connect(self.directory / 'relay.db', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT, password TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, epoch TEXT, value INTEGER);
        CREATE TABLE IF NOT EXISTS traffic(ts INTEGER, uid TEXT, protocol TEXT, direction TEXT, bytes INTEGER);
        CREATE INDEX IF NOT EXISTS traffic_time ON traffic(ts);
        CREATE TABLE IF NOT EXISTS audit(ts INTEGER, action TEXT);''')
        self.db.commit()
        from cloudflare import Cloudflare
        self.cloudflare = Cloudflare(self)
    def load(self):
        row = self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
        if not row: raise ValueError('尚未初始化')
        return json.loads(row[0])
    def totals(self, monthly=False):
        since = 0
        if monthly:
            now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
            since = int(now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp())
        return dict(self.db.execute('SELECT uid,SUM(bytes) FROM traffic WHERE ts>=? GROUP BY uid', (since,)).fetchall())
    def apply(self, state):
        validate(state, (self.settings['web_port'], self.settings['api_port'], self.settings['stats_port']))
        if self.apply_callback: return self.apply_callback(state)
        if not self.settings.get('production'): return
        atomic(self.directory / 'pending.json', {'state': state, 'usage': self.totals(monthly=True)})
        proc = subprocess.run(['sudo', '-n', '/opt/relay/venv/bin/python', '/opt/relay/backend/apply.py'], capture_output=True, text=True, timeout=90)
        if proc.returncode: raise ValueError('内核配置应用失败，已尝试恢复旧配置；请检查 relay-sing-box 服务日志')
    def mutate(self, action, payload):
        with self.lock:
            if self.settings.get('production'): self.collect()
            old = self.load(); s = copy.deepcopy(old)
            if payload.get('revision') != s['revision']: raise ValueError('数据已更新，请刷新后重试')
            if action == 'user-create':
                protocols = payload.get('protocols', [])
                if not protocols: raise ValueError('至少选择一种协议')
                s['users'].append({'id': secrets.token_hex(8), 'name': str(payload['name']).strip(), 'active': True, 'expire': payload['expire'], 'quota': None if payload['quota'] is None else float(payload['quota']), 'token': secrets.token_urlsafe(32), 'credentials': {n: credential(n) for n in protocols}})
            elif action.startswith('user-'):
                u = next((u for u in s['users'] if u['id'] == payload.get('id')), None)
                if not u: raise ValueError('用户不存在')
                if action == 'user-update':
                    for field in ('name', 'active', 'expire', 'quota'):
                        if field in payload: u[field] = payload[field]
                    if 'protocols' in payload: u['credentials'] = {n: u['credentials'].get(n) or credential(n) for n in payload['protocols']}
                elif action == 'user-reset':
                    n = payload['protocol']
                    if n not in u['credentials']: raise ValueError('此用户未获授权')
                    u['credentials'][n] = credential(n)
                elif action == 'user-token': u['token'] = secrets.token_urlsafe(32)
                elif action == 'user-delete': s['users'].remove(u)
                else: raise ValueError('不支持的操作')
            elif action == 'protocol-update':
                n = payload['name']; p = next((p for p in s['protocols'] if p['name'] == n), None)
                if not p: raise ValueError('协议不存在')
                for field in ('active', 'port'):
                    if field in payload: p[field] = payload[field]
            elif action == 'routing-update':
                s['rules'] = payload['rules']; s['fallback'] = payload['fallback']
            else: raise ValueError('不支持的操作')
            s['revision'] += 1
            self.apply(s)
            with self.db:
                self.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(s),))
                self.db.execute('INSERT INTO audit VALUES(?,?)', (int(time.time()), action))
            self.eligibility = tuple(u['id'] for u in s['users'] if eligible(u, self.totals(monthly=True)))
            self.cloudflare.changed()
            return self.public_state()
    def collect(self):
        from stats import query
        try:
            generation_path = Path(self.settings.get('generation_file', '/etc/relay/generation'))
            def read_epoch():
                if not self.settings.get('production'): return generation_path.read_text().strip()
                result = subprocess.run(['systemctl', 'show', '-p', 'ExecMainStartTimestampMonotonic', 'relay-sing-box'], capture_output=True, text=True, timeout=3)
                value = result.stdout.partition('=')[2].strip()
                return value if result.returncode == 0 and value not in ('', '0') else generation_path.read_text().strip()
            epoch = read_epoch()
            values = query(self.settings['stats_port'])
            if read_epoch() != epoch: return
            self.record(values, epoch)
            self.stats_status = '正常'; self.last_sample = int(time.time())
        except Exception:
            self.stats_status = '采集不可用，请检查内核是否包含 with_v2ray_api 及本机统计接口'
    def record(self, values, epoch):
        with self.lock, self.db:
            for name, value in values.items():
                m = re.fullmatch(r'user>>>([a-zA-Z0-9_-]+):([a-z0-9]+)>>>traffic>>>(uplink|downlink)', name)
                if not m or not isinstance(value, int) or value < 0: continue
                prev = self.db.execute('SELECT epoch,value FROM counters WHERE name=?', (name,)).fetchone()
                delta = value if not prev or prev[0] != epoch or value < prev[1] else value-prev[1]
                self.db.execute('INSERT OR REPLACE INTO counters VALUES(?,?,?)', (name, epoch, value))
                if delta: self.db.execute('INSERT INTO traffic VALUES(?,?,?,?,?)', (int(time.time()), *m.groups(), delta))
    def traffic_snapshot(self):
        with self.lock:
            now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
            since = int(now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp())
            rows = self.db.execute('SELECT uid,direction,SUM(bytes) FROM traffic WHERE ts>=? GROUP BY uid,direction', (since,)).fetchall()
            users = {u['id']: {'id':u['id'],'upload_bytes':0,'download_bytes':0,'used_bytes':0} for u in self.load()['users']}
            directions = {'uplink':0,'downlink':0}
            for uid, direction, amount in rows:
                if direction not in directions: continue
                directions[direction] += amount
                if uid in users:
                    users[uid]['upload_bytes' if direction=='uplink' else 'download_bytes'] += amount
                    users[uid]['used_bytes'] += amount
            usage = {uid:r['used_bytes'] for uid,r in users.items()}
            for u in self.load()['users']:
                users[u['id']]['effective'] = eligible(u, usage)
            stats = {'status':self.stats_status, 'last_sample':self.last_sample, 'sample_interval':10, 'month_bytes':sum(directions.values()), 'directions':directions, 'history':self.db.execute('SELECT (ts/3600)*3600,direction,SUM(bytes) FROM traffic WHERE ts>? GROUP BY 1,2 ORDER BY 1', (int(time.time())-86400,)).fetchall()}
            return {'users':list(users.values()), 'stats':stats}
    def public_state(self):
        with self.lock:
            s = self.load(); traffic = self.traffic_snapshot()
            by_id = {u['id']:u for u in traffic['users']}
            for u in s['users']:
                u.update(by_id[u['id']])
                u['used'] = round(u['used_bytes'] / 1024**3, 4)
                u['subscription'] = self.cloudflare.subscription_base() + '/' + u['token']
            s['stats'] = traffic['stats']
            s['server'] = {'preview':self.settings.get('preview',False), 'host': self.settings['host'], 'production': self.settings.get('production', False), 'vmess_tls':self.settings.get('vmess_tls',False), 'tls_name':self.settings.get('tls_name','www.bing.com'), 'reality_sni':self.settings['reality_sni'], 'vmess_ws_path':self.settings.get('vmess_ws_path','/relay-vmess')}
            return s
    def enforce(self):
        """Reapply only when expiry/quota eligibility changes, with at most sampling delay."""
        with self.lock:
            s = self.load(); usage = self.totals(monthly=True)
            signature = tuple(u['id'] for u in s['users'] if eligible(u, usage))
            if getattr(self, 'eligibility', signature) != signature:
                self.apply(s)
            self.eligibility = signature

class Handler(BaseHTTPRequestHandler):
    server_version = 'Relay'
    def log_message(self, *_): pass  # Request URLs may contain subscription bearer tokens.
    def respond(self, status, obj, headers=None, kind='application/json'):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        for k, v in {'Content-Type': kind, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'", **(headers or {})}.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def session(self):
        cookie = http.cookies.SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError: return None
        token = cookie.get('relay_session')
        if not token: return None
        digest = hashlib.sha256(token.value.encode()).hexdigest()
        with self.server.store.lock:
            row = self.server.store.db.execute('SELECT csrf FROM sessions WHERE token=? AND expires>?', (digest, time.time())).fetchone()
        return (digest, row[0]) if row else None
    def app_path(self):
        path = urlsplit(self.path).path
        prefix = self.server.store.settings.get('base_path', '')
        if prefix and path == prefix: return ''
        if prefix and not path.startswith(prefix + '/'): return None
        return path[len(prefix):]
    def cookie_path(self):
        return self.server.store.settings.get('base_path', '') + '/'
    def do_GET(self):
        try:
            url = urlsplit(self.path); path = self.app_path(); store = self.server.store
            if path is None: return self.respond(404, b'Not found', kind='text/plain')
            if path == '': return self.respond(308, b'', {'Location': self.cookie_path()}, 'text/plain')
            if path == '/api/health': return self.respond(200, {'ok': True})
            if path.startswith('/sub/'):
                token = path.split('/')[-1]
                with store.lock:
                    s = store.load(); u = next((u for u in s['users'] if hmac.compare_digest(u['token'], token)), None)
                    usage = store.totals(monthly=True)
                    if not u or not eligible(u, usage): return self.respond(404, {'error': '订阅不可用'})
                    fmt = parse_qs(url.query).get('format', ['uri'])[0]
                    body, kind = subscription(s, u, store.settings, fmt, usage)
                    month = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
                    row = dict(store.db.execute('SELECT direction,SUM(bytes) FROM traffic WHERE uid=? AND ts>=? GROUP BY direction', (u['id'],int(month.timestamp()))))
                    _, info = subscription_limits(u, row.get('uplink',0), row.get('downlink',0))
                    return self.respond(200, body, {'Subscription-Userinfo': info, 'profile-update-interval': '6'}, kind)
            if path.startswith('/api/'):
                session = self.session()
                if not session: return self.respond(401, {'error': '请先登录'})
                if path == '/api/session': return self.respond(200, {'csrf': session[1]})
                if path == '/api/state': return self.respond(200, store.public_state())
                if path == '/api/traffic': return self.respond(200, store.traffic_snapshot())
                if path == '/api/frontend-version': return self.respond(200, {'version':current_frontend(ROOT)[1],'api_version':API_VERSION})
                if path == '/api/cloudflare': return self.respond(200, store.cloudflare.public())
                if path == '/api/metrics': return self.respond(200, store.monitor.snapshot())
                if path == '/api/share':
                    uid = parse_qs(url.query).get('id', [''])[0]
                    with store.lock:
                        state = store.load(); usage = store.totals(monthly=True)
                        user = next((u for u in state['users'] if u['id'] == uid), None)
                        if not user: return self.respond(404, {'error':'用户不存在'})
                        if not eligible(user, usage): return self.respond(400, {'error':'此用户当前不可用'})
                        content, _ = subscription(state, user, store.settings, 'uri', usage)
                        reverse = {kind:name for name,kind in KINDS.items()}
                        nodes = [{'protocol':reverse[urlsplit(uri).scheme], 'uri':uri} for uri in base64.b64decode(content).decode().splitlines()]
                        return self.respond(200, {'id':uid, 'nodes':nodes})
                if path == '/api/audit':
                    with store.lock: rows = store.db.execute('SELECT ts,action FROM audit ORDER BY ts DESC LIMIT 100').fetchall()
                    return self.respond(200, rows)
                return self.respond(404, {'error': '接口不存在'})
            import mimetypes
            directory,version=current_frontend(ROOT)
            cache={}
            if path=='/': file=directory/'index.html'
            elif path.startswith('/assets/'):
                parts=path.split('/',3)
                if len(parts)!=4:return self.respond(404,b'Not found',kind='text/plain')
                try:file=frontend_asset(ROOT,parts[2],parts[3])
                except (ValueError,FileNotFoundError):return self.respond(404,b'Not found',kind='text/plain')
                cache={'Cache-Control':'public, max-age=31536000, immutable'}
            elif path[1:] in ASSETS:file=directory/path[1:]
            else:return self.respond(404,b'Not found',kind='text/plain')
            kind={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}[file.suffix]
            body=file.read_bytes()
            if path=='/':
                prefix=store.settings.get('base_path','')
                asset_base=prefix+'/assets/'+version+'/'
                flags='<script>window.RELAY_LIVE=true;window.RELAY_BASE_PATH='+json.dumps(prefix)+';window.RELAY_FRONTEND_VERSION='+json.dumps(version)+';</script>'
                body=body.replace(b'<body>',b'<body class="login-mode">').replace(b'<script src="app.js"></script>',flags.encode()+b'<script src="app.js"></script><script src="live.js"></script>')
                for name in ASSETS:
                    for attribute in ('src','href'):
                        body=body.replace((attribute+'="'+name+'"').encode(),(attribute+'="'+asset_base+name+'"').encode())
            return self.respond(200,body,cache,kind)
        except (ValueError, AssertionError, KeyError, TypeError): self.respond(400, {'error': '参数或格式无效'})
        except Exception: self.respond(500, {'error': '服务错误，请检查后台日志'})
    def do_POST(self):
        store = self.server.store
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1_000_000: return self.respond(413, {'error': '请求体无效'})
            public = urlsplit(store.settings['public_url'])
            expected = public.scheme + '://' + public.netloc
            path = self.app_path()
            if path is None or path == '': return self.respond(404, {'error':'接口不存在'})
            if self.headers.get('Origin') != expected: return self.respond(403, {'error': '请求来源无效'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': return self.respond(415, {'error': '需要 JSON'})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict): raise ValueError('请求体无效')
            if path == '/api/login':
                with store.lock:
                    now = time.time(); attempts = self.server.attempts
                    attempts[:] = [t for t in attempts if t > now-300]
                    if len(attempts) >= 15: return self.respond(429, {'error': '尝试次数过多，请五分钟后重试'})
                    attempts.append(now)
                    row = store.db.execute('SELECT username,password FROM admin WHERE id=1').fetchone()
                    valid = check_password(str(payload.get('password', '')), row[1])
                    if not valid or not hmac.compare_digest(str(payload.get('username', '')), row[0]): return self.respond(401, {'error': '账号或密码不正确'})
                    token = secrets.token_urlsafe(32); csrf = secrets.token_urlsafe(32)
                    with store.db:
                        store.db.execute('DELETE FROM sessions WHERE expires<?', (now,))
                        store.db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, now+28800))
                    secure = '; Secure' if expected.startswith('https://') else ''
                    return self.respond(200, {'csrf': csrf}, {'Set-Cookie': f'relay_session={token}; HttpOnly; SameSite=Strict; Path={self.cookie_path()}; Max-Age=28800{secure}'})
            session = self.session()
            if not session: return self.respond(401, {'error': '请先登录'})
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session[1]): return self.respond(403, {'error': 'CSRF 校验失败'})
            if path == '/api/logout':
                with store.lock, store.db: store.db.execute('DELETE FROM sessions WHERE token=?', (session[0],))
                return self.respond(200, {'ok': True}, {'Set-Cookie': f'relay_session=; HttpOnly; SameSite=Strict; Path={self.cookie_path()}; Max-Age=0'})
            if path == '/api/cloudflare/register': return self.respond(200, store.cloudflare.register(payload))
            if path == '/api/cloudflare/configure': return self.respond(200, store.cloudflare.configure(payload))
            if path == '/api/cloudflare/sync': return self.respond(200, store.cloudflare.sync(payload))
            if path == '/api/export':
                ids = payload.get('ids', [])
                if not isinstance(ids,list) or not all(isinstance(x,str) for x in ids): raise ValueError('用户选择无效')
                mode=payload.get('mode','subscription');fmt=payload.get('format','karing')
                if mode not in ('subscription','node') or fmt not in ('uri','karing','mihomo','singbox'):raise ValueError('导出格式无效')
                with store.lock:
                    state=store.load();usage=store.totals(monthly=True);public_users={u['id']:u for u in store.public_state()['users']};lines=[];skipped=[]
                    if set(ids)-set(public_users):raise ValueError('用户不存在，请刷新')
                    for u in state['users']:
                        if u['id'] not in ids:continue
                        if not eligible(u,usage):skipped.append(u['name']);continue
                        name=re.sub(r'\s+',' ',u['name']).strip()
                        if mode=='subscription':lines.append(name+' '+public_users[u['id']]['subscription']+'?format='+fmt)
                        else:
                            body,_=subscription(state,u,store.settings,'uri',usage)
                            lines.extend(name+' '+uri for uri in base64.b64decode(body).decode().splitlines())
                return self.respond(200, {'text':'\n'.join(lines),'skipped':skipped})
            if path == '/api/action': return self.respond(200, store.mutate(payload['action'], payload))
            return self.respond(404, {'error': '接口不存在'})
        except (ValueError, AssertionError, KeyError, TypeError) as exc: self.respond(400, {'error': str(exc) or '输入无效'})
        except Exception: self.respond(500, {'error': '操作失败，请检查服务日志'})

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('command', choices=['init', 'serve', 'reset-password']); parser.add_argument('--settings', default='/etc/relay/settings.json'); args = parser.parse_args()
    settings = json.loads(Path(args.settings).read_text()); os.umask(0o077); store = Store(settings)
    if args.command in ('init', 'reset-password'):
        import getpass
        username = os.environ.get('ADMIN_USER') or input('管理员账号：').strip()
        password = getpass.getpass('管理员密码：')
        if password != getpass.getpass('再次输入密码：'): raise SystemExit('两次密码不一致')
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,32}', username): raise SystemExit('账号需要 3–32 位字母、数字、下划线或短横线')
        encoded = password_hash(password)
        with store.lock, store.db:
            if args.command == 'init' and store.db.execute('SELECT 1 FROM admin').fetchone(): raise SystemExit('管理员已存在')
            store.db.execute('INSERT OR REPLACE INTO admin VALUES(1,?,?)', (username, encoded)); store.db.execute('DELETE FROM sessions')
            store.db.execute('INSERT OR IGNORE INTO state VALUES(1,?)', (json.dumps(initial(settings.get('ports'))),))
        return
    store.load()
    store.monitor.start()
    store.cloudflare.start()
    if settings.get('production'): store.apply(store.load())
    def poll():
        while True:
            with store.lock:
                if settings.get('production'): store.collect()
                try: store.enforce()
                except Exception: store.stats_status = '到期/额度策略应用失败，请检查服务状态'
            time.sleep(10)
    threading.Thread(target=poll, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', settings['api_port']), Handler); server.store = store; server.attempts = []
    server.serve_forever()

if __name__ == '__main__': main()
