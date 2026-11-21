"""Installer-only initialization; plaintext password is received over stdin."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import uuid
from app import Store, atomic, password_hash
from model import initial, PORTS, validate
from web import validate_path

if os.geteuid() != 0: raise SystemExit('root required')
settings_path = Path('/etc/relay/settings.json')
if settings_path.exists(): raise SystemExit('Refusing to overwrite an existing installation')
password = sys.stdin.read(1025)
encoded = password_hash(password)
username = os.environ['ADMIN_USER']
if not re.fullmatch(r'[A-Za-z0-9_-]{3,32}', username): raise SystemExit('Invalid username')
result = subprocess.run(['/opt/relay/bin/sing-box', 'generate', 'reality-keypair'], capture_output=True, text=True, check=True)
keys = dict(re.findall(r'(PrivateKey|PublicKey):\s*(\S+)', result.stdout))
settings = {'production': True, 'data': '/var/lib/relay', 'web_port': int(os.environ['WEB_PORT']), 'api_port': 18090, 'stats_port': 18091, 'public_url': f'https://{os.environ["PUBLIC_HOST"]}:{os.environ["WEB_PORT"]}', 'host': os.environ['PUBLIC_HOST'], 'tls_name': os.environ['PUBLIC_HOST'], 'self_signed': os.environ['SELF_SIGNED'] == 'true', 'cert': '/etc/relay/node-cert.pem', 'key': '/etc/relay/node-key.pem', 'reality_private': keys['PrivateKey'], 'reality_public': keys['PublicKey'], 'reality_sni': 'www.apple.com', 'short_id': secrets.token_hex(4), 'ports': {n: int(os.environ[{'VMess':'VMESS_PORT','TUIC v5':'TUIC_PORT','VLESS':'VLESS_PORT','Hysteria2':'HYSTERIA2_PORT','AnyTLS':'ANYTLS_PORT'}[n]]) for n in PORTS}}
settings.update({'tls_name':os.environ.get('TLS_SERVER_NAME') or 'www.bing.com', 'reality_sni':os.environ.get('REALITY_SNI','apple.com'), 'reality_handshake_host':os.environ.get('REALITY_HANDSHAKE_HOST','apple.com'), 'reality_handshake_port':int(os.environ.get('REALITY_HANDSHAKE_PORT','443')), 'vmess_tls':os.environ.get('VMESS_TLS','false')=='true', 'vmess_ws_path':os.environ.get('VMESS_WS_PATH') or (str(uuid.uuid4())+'-vm'), 'tuic_congestion_control':os.environ.get('TUIC_CONGESTION_CONTROL','bbr')})
for field in ('tls_name','reality_sni','reality_handshake_host'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',settings[field]):raise SystemExit('Invalid SNI/handshake host')
assert 1 <= settings['reality_handshake_port'] <= 65535
assert len(settings['vmess_ws_path'])<=256 and not any(ord(c)<32 for c in settings['vmess_ws_path'])
assert settings['tuic_congestion_control'] in ('bbr','cubic','new_reno')
assert os.environ.get('VMESS_TLS','false') in ('true','false')
settings['base_path']=validate_path(os.environ['ADMIN_PATH'])
settings['public_url']+=settings['base_path']
state = initial(settings['ports']); validate(state, (settings['web_port'],18090,18091))
store = Store(settings)
with store.db:
    store.db.execute('INSERT INTO admin VALUES(1,?,?)', (username, encoded))
    store.db.execute('INSERT INTO state VALUES(1,?)', (json.dumps(state),))
atomic(settings_path, settings)
