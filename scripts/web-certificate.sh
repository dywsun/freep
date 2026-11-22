#!/usr/bin/env bash
# Sourced by install.sh. Nginx on port 80 serves challenge files only.
write_relay_nginx() {
  local phase="${1:-final}"
  /opt/relay/venv/bin/python - "$PUBLIC_HOST" "$WEB_PORT" "$API_PORT" "$ADMIN_PATH" "$phase" <<'PY'
import sys
sys.path.insert(0,'/opt/relay/backend')
from web import nginx_config
from pathlib import Path
Path('/etc/nginx/conf.d/relay.conf').write_text(nginx_config(sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4],challenge_only=sys.argv[5]=='challenge'))
PY
}

# Nginx reload is asynchronous; the master can acknowledge before new workers serve requests.
wait_relay_challenge() {
  local scope="$1" probe="$2" expected="$3" attempt reply status
  local options=()
  if [[ $scope == local ]]; then
    options=(--resolve "$PUBLIC_HOST:80:127.0.0.1")
  fi
  for ((attempt=1; attempt<=10; attempt++)); do
    reply=''
    if reply="$(curl --silent --ipv4 --noproxy '*' --connect-timeout 3 --max-time 8 ${options[@]+"${options[@]}"} --write-out $'\n%{http_code}' "http://$PUBLIC_HOST/.well-known/acme-challenge/$probe")"; then
      status="${reply##*$'\n'}"
      if [[ $status == 200 && ${reply%$'\n'*} == "$expected" ]]; then return 0; fi
    else
      status="${reply##*$'\n'}"
    fi
    if [[ $attempt -lt 10 ]]; then
      echo "等待证书验证入口就绪：${scope}，尝试 ${attempt}/10（HTTP ${status:-000}）" >&2
      sleep 1
    fi
  done
  echo "证书验证入口检查失败：${scope}（HTTP ${status:-000}，或响应内容不匹配）。" >&2
  return 1
}

prepare_web_certificate() {
  install -d -m 755 /var/lib/relay-acme /var/lib/relay-acme/.well-known /var/lib/relay-acme/.well-known/acme-challenge
  install -d -m 700 /etc/relay/acme-deploy /etc/relay/acme
  printf '%s\n' "$PUBLIC_HOST" > /etc/relay/web-domain
  chmod 600 /etc/relay/web-domain
  write_relay_nginx challenge
  configure_selinux
  configure_firewall
  nginx -t
  systemctl enable nginx
  if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
  if [[ -n $WEB_TLS_CERT || -n $WEB_TLS_KEY ]]; then
    [[ -f $WEB_TLS_CERT && -f $WEB_TLS_KEY ]] || { echo 'WEB_TLS_CERT/WEB_TLS_KEY 必须同时提供'; return 1; }
    install -m 644 "$WEB_TLS_CERT" /etc/relay/acme-deploy/fullchain.pem
    install -m 600 "$WEB_TLS_KEY" /etc/relay/acme-deploy/key.pem
    bash /opt/relay/scripts/deploy-web-cert.sh
    echo '使用已提供并通过信任链、域名校验的网站证书；续期由证书提供方负责。'
    return
  fi
  /opt/relay/venv/bin/python - "$PUBLIC_HOST" <<'PY'
import ipaddress,socket,sys
host=sys.argv[1]
try: ipaddress.ip_address(host)
except ValueError: pass
else: raise SystemExit('自动申请模式请使用域名，而非 IP 地址')
records=socket.getaddrinfo(host,80,type=socket.SOCK_STREAM)
if not any(r[0]==socket.AF_INET for r in records):raise SystemExit('未解析到 A 记录，请先在 Cloudflare 配置 A 记录并等待生效')
print('域名解析地址：'+', '.join(sorted({r[4][0] for r in records})))
PY
  local probe token
  token="$(openssl rand -hex 24)"
  probe="relay-check-$(openssl rand -hex 8)"
  printf '%s' "$token" > "/var/lib/relay-acme/.well-known/acme-challenge/$probe"
  chmod 644 "/var/lib/relay-acme/.well-known/acme-challenge/$probe"
  if ! wait_relay_challenge local "$probe" "$token" || ! wait_relay_challenge public "$probe" "$token"; then
    rm -f "/var/lib/relay-acme/.well-known/acme-challenge/$probe"
    echo '域名验证入口不可达：检查 A 记录、Cloudflare 灰云及公网 TCP 80。未开放管理网站。' >&2
    return 1
  fi
  rm -f "/var/lib/relay-acme/.well-known/acme-challenge/$probe"
  curl --fail --location --proto '=https' --tlsv1.2 'https://github.com/acmesh-official/acme.sh/archive/refs/tags/3.1.7.tar.gz' -o "$relay_tmp/acme.tar.gz"
  tar -xzf "$relay_tmp/acme.tar.gz" -C "$relay_tmp"
  local account_args=()
  if [[ -n $ACME_EMAIL ]]; then account_args=(--accountemail "$ACME_EMAIL"); fi
  (cd "$relay_tmp/acme.sh-3.1.7"; bash ./acme.sh --install --home /opt/relay/acme --config-home /etc/relay/acme --nocron --noprofile ${account_args[@]+"${account_args[@]}"})
  chmod 700 /opt/relay/acme /etc/relay/acme
  # Public challenge files need to be readable by Nginx workers.
  local issue_status=0
  (umask 022; /opt/relay/acme/acme.sh --issue --home /opt/relay/acme --config-home /etc/relay/acme --server letsencrypt --keylength ec-256 --webroot /var/lib/relay-acme -d "$PUBLIC_HOST" ${account_args[@]+"${account_args[@]}"}) || issue_status=$?
  # acme.sh exit 2 means the existing certificate does not yet need renewal.
  if [[ $issue_status != 0 && $issue_status != 2 ]]; then
    echo '网站证书申请失败，停止安装；不会降级到 HTTP 或自签网站证书。' >&2
    return 1
  fi
  /opt/relay/acme/acme.sh --install-cert --home /opt/relay/acme --config-home /etc/relay/acme -d "$PUBLIC_HOST" --ecc --fullchain-file /etc/relay/acme-deploy/fullchain.pem --key-file /etc/relay/acme-deploy/key.pem --reloadcmd 'bash /opt/relay/scripts/deploy-web-cert.sh'
  # A timer replaces acme.sh's cron entry, including on CentOS 7.
  cat > /etc/systemd/system/relay-acme.service <<'UNIT'
[Unit]
Description=Renew Relay website certificate
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/opt/relay/acme/acme.sh --cron --home /opt/relay/acme --config-home /etc/relay/acme
UNIT
  cat > /etc/systemd/system/relay-acme.timer <<'UNIT'
[Unit]
Description=Check Relay website certificate twice daily
[Timer]
OnCalendar=*-*-* 03,15:15:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now relay-acme.timer
}
