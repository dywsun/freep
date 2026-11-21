#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
data = root / '.local'
data.mkdir(exist_ok=True, mode=0o700)
settings = data / 'settings.json'
if not settings.exists():
    settings.write_text(json.dumps({'production':False,'data':str(data),'host':'node.example.com','tls_name':'node.example.com','self_signed':True,'public_url':'http://127.0.0.1:18092','web_port':18898,'api_port':18092,'stats_port':18091,'cert':'/etc/relay/cert.pem','key':'/etc/relay/key.pem','reality_private':'dev-only','reality_public':'dev-only','reality_sni':'www.apple.com','short_id':'abcd'})); settings.chmod(0o600)
app = [sys.executable, str(root/'backend/app.py')]
if not (data/'relay.db').exists(): subprocess.run(app+['init','--settings',str(settings)],check=True)
print('Relay 开发后台：http://127.0.0.1:18092',flush=True)
subprocess.run(app+['serve','--settings',str(settings)],check=True)
