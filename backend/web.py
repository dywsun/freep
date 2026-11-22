"""Shared validation and deterministic Nginx configuration generation."""
import re


def validate_path(path):
    if not isinstance(path, str) or len(path) > 128 or not re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', path):
        raise ValueError('后台路径必须以 / 开头，仅包含字母、数字、短横线、下划线；不能为根路径或以 / 结尾')
    return path


def nginx_config(host, web_port, api_port, base_path='', challenge_only=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host): raise ValueError('无效域名')
    if web_port == 8443: raise ValueError('8443 is reserved for subscription origin')
    if base_path: validate_path(base_path)
    for port in (web_port, api_port):
        if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('无效端口')
    challenge = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {host};
    access_log off;
    location ^~ /.well-known/acme-challenge/ {{
        root /var/lib/relay-acme;
        default_type text/plain;
        try_files $uri =404;
    }}
    location / {{ return 404; }}
}}
'''
    if challenge_only: return challenge
    panel = f'''server {{
    listen {web_port} ssl default_server;
    listen [::]:{web_port} ssl default_server;
    server_name {host};
    ssl_certificate /etc/relay/web-cert.pem;
    ssl_certificate_key /etc/relay/web-key.pem;
    ssl_protocols TLSv1.2;
    client_max_body_size 1m;
    access_log off;
    location = {base_path or '/'} {{ return 308 {base_path}/; }}
    location ^~ {base_path}/ {{
        proxy_pass http://127.0.0.1:{api_port};
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 100s;
    }}
    location / {{ return 404; }}
}}
'''

    subscription_origin = f'''server {{
    listen 8443 ssl;
    error_log /dev/null crit;
    listen [::]:8443 ssl;
    server_name {host};
    ssl_certificate /etc/relay/web-cert.pem;
    ssl_certificate_key /etc/relay/web-key.pem;
    ssl_protocols TLSv1.2;
    access_log off;
    location ^~ {base_path}/sub/ {{
        limit_except GET {{ deny all; }}
        proxy_pass http://127.0.0.1:{api_port};
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 15s;
    }}
    location / {{ return 404; }}
}}
'''
    return challenge + panel + subscription_origin
