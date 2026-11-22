#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# Edit these defaults or export matching variables before running the installer.
VMESS_PORT="${VMESS_PORT:-8880}"
TUIC_PORT="${TUIC_PORT:-32786}"
VLESS_PORT="${VLESS_PORT:-10443}"
HYSTERIA2_PORT="${HYSTERIA2_PORT:-10444}"
ANYTLS_PORT="${ANYTLS_PORT:-10446}"
WEB_PORT="${WEB_PORT:-18898}"
API_PORT=18090
STATS_PORT=18091
SB_VERSION="${SB_VERSION:-1.14.4}"
# Website DNS name. Create a Cloudflare A record before installation.
PUBLIC_HOST="${PUBLIC_HOST:-free.dywsun.dpdns.org}"
ACME_EMAIL="${ACME_EMAIL:-}"
TLS_CERT="${TLS_CERT:-}"
TLS_KEY="${TLS_KEY:-}"
TLS_SERVER_NAME="${TLS_SERVER_NAME:-www.bing.com}"
WEB_TLS_CERT="${WEB_TLS_CERT:-}"
WEB_TLS_KEY="${WEB_TLS_KEY:-}"
REALITY_SNI="${REALITY_SNI:-apple.com}"
REALITY_HANDSHAKE_HOST="${REALITY_HANDSHAKE_HOST:-$REALITY_SNI}"
REALITY_HANDSHAKE_PORT="${REALITY_HANDSHAKE_PORT:-443}"
VMESS_TLS="${VMESS_TLS:-false}"
VMESS_WS_PATH="${VMESS_WS_PATH:-}"
TUIC_CONGESTION_CONTROL="${TUIC_CONGESTION_CONTROL:-bbr}"
RELAY_REPO="${RELAY_REPO:-dywsun/freep}"
RELAY_REF="${RELAY_REF:-main}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $EUID == 0 ]] || { echo '请使用 root 执行安装器'; exit 1; }
[[ -r /etc/os-release ]] || exit 1
source /etc/os-release
[[ ${ID:-} =~ ^(debian|ubuntu|centos)$ ]] || { echo '支持 Ubuntu 22.04+/Debian 12+ 与 CentOS 7/8/Stream 9/10（systemd）'; exit 1; }
command -v systemctl >/dev/null || { echo '需要 systemd'; exit 1; }
command="${1:-install}"
if [[ $command == update-web ]]; then
  updater="$SCRIPT_DIR/scripts/update_frontend.py"
  [[ -f $updater ]] || updater=/opt/relay/scripts/update_frontend.py
  [[ -f $updater ]] || { echo '未安装支持前端更新的版本，请先升级后端'; exit 1; }
  exec /opt/relay/venv/bin/python "$updater" --repo "$RELAY_REPO" --ref "$RELAY_REF"
fi
if [[ $command == reset-password ]]; then
  exec sudo -u relay-panel /opt/relay/venv/bin/python /opt/relay/backend/app.py reset-password
fi
if [[ $command == status ]]; then
  systemctl status relay-panel relay-sing-box nginx --no-pager; exit
fi
if [[ $command == backup ]]; then
  backup_file="/root/relay-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
  systemctl stop relay-panel
  trap 'systemctl start relay-panel' EXIT
  tar -czf "$backup_file" /etc/relay /var/lib/relay
  echo "备份已保存：$backup_file（包含私钥和用户凭据，请保密）"; exit
fi
[[ $command == install ]] || { echo '支持：install / status / backup / reset-password / update-web'; exit 1; }
[[ ! -e /etc/relay/settings.json && ! -e /var/lib/relay/relay.db ]] || { echo '检测到已有部署，拒绝覆盖；请先备份，升级需使用专用迁移流程。'; exit 1; }
# First interactive step, before package installation or any service changes.
[[ -r /dev/tty ]] || { echo '首次安装需要交互终端设置管理员'; exit 1; }
while true; do
  read -r -p '设置管理员账号（3–32 位字母/数字/_/-）：' ADMIN_USER </dev/tty
  [[ $ADMIN_USER =~ ^[A-Za-z0-9_-]{3,32}$ ]] || continue
  read -r -s -p '设置管理员密码（至少 12 个字符）：' admin_password </dev/tty; echo
  read -r -s -p '再次输入管理员密码：' admin_password_confirm </dev/tty; echo
  if [[ ${#admin_password} -ge 12 && ${#admin_password} -le 256 && $admin_password == "$admin_password_confirm" ]]; then break; fi
  echo '密码长度不合要求或两次不一致，请重新设置。'
done
unset admin_password_confirm
while true; do
  read -r -p '设置后台访问路径（例如 /freedom-network）：' ADMIN_PATH </dev/tty
  if [[ ${#ADMIN_PATH} -le 128 && $ADMIN_PATH =~ ^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$ ]]; then break; fi
  echo '路径必须以 / 开头，不能为根路径或以 / 结尾，仅支持字母、数字、短横线、下划线。'
done
export ADMIN_PATH
[[ $PUBLIC_HOST =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo '请先 export PUBLIC_HOST=你的域名或公网IPv4'; exit 1; }
[[ $SB_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
ports=()
for value in "$VMESS_PORT" "$TUIC_PORT" "$VLESS_PORT" "$HYSTERIA2_PORT" "$ANYTLS_PORT" "$WEB_PORT" "$API_PORT" "$STATS_PORT"; do
  [[ $value =~ ^[0-9]{1,5}$ && $value -ge 1024 && $value -le 65535 ]] || { echo "端口无效：$value"; exit 1; }
  for prior in "${ports[@]:-}"; do [[ $prior != "$value" ]] || { echo "端口重复：$value"; exit 1; }; done
  ports+=("$value")
  if command -v ss >/dev/null && ss -H -lntu | awk '{print $5}' | grep -Eq ":${value}$"; then echo "端口已占用：$value"; exit 1; fi
done
if command -v ss >/dev/null && ss -H -lnt | awk '{print $4}' | grep -Eq ':443$'; then
  echo '443 端口已占用，无法创建独立订阅 HTTPS 回源入口，请先检查现有服务。'; exit 1
fi
if [[ -n $TLS_CERT || -n $TLS_KEY ]]; then
  [[ -f $TLS_CERT && -f $TLS_KEY ]] || { echo 'TLS_CERT/TLS_KEY 必须同时指定有效文件'; exit 1; }
fi
case "$(uname -m)" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) echo '仅支持 amd64/arm64'; exit 1;; esac
install -d -m 755 /opt/relay /opt/relay/bin /etc/relay
relay_tmp="$(mktemp -d)"
trap 'rm -rf -- "$relay_tmp"; unset admin_password' EXIT
if [[ -f $SCRIPT_DIR/backend/app.py ]]; then
  cp -R "$SCRIPT_DIR/backend" "$SCRIPT_DIR/frontend" "$SCRIPT_DIR/scripts" /opt/relay/
else
  [[ $RELAY_REPO =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo '仓库名无效'; exit 1; }
  if [[ ! $RELAY_REF =~ ^[a-f0-9]{40}$ ]]; then
    [[ $RELAY_REF =~ ^[A-Za-z0-9_.-]+$ ]] || { echo '分支或版本标识无效'; exit 1; }
    echo "正在解析 $RELAY_REPO 的 $RELAY_REF 版本……"
    RELAY_REF="$(curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 -H 'Accept: application/vnd.github.sha' "https://api.github.com/repos/$RELAY_REPO/commits/$RELAY_REF")" || {
      echo '无法解析仓库版本：请确认仓库公开且已经上传代码，或稍后重试 GitHub API。' >&2
      exit 1
    }
    [[ $RELAY_REF =~ ^[a-f0-9]{40}$ ]] || { echo 'GitHub 返回的提交编号无效，停止安装'; exit 1; }
  fi
  echo "安装源码版本：$RELAY_REF"
  curl --fail --location --proto '=https' --tlsv1.2 "https://github.com/$RELAY_REPO/archive/$RELAY_REF.tar.gz" -o "$relay_tmp/source.tar.gz"
  tar -xzf "$relay_tmp/source.tar.gz" -C "$relay_tmp"
  cp -R "$relay_tmp"/*/backend "$relay_tmp"/*/frontend "$relay_tmp"/*/scripts /opt/relay/
fi

source /opt/relay/scripts/os-packages.sh
install_os_packages
id relay-panel >/dev/null 2>&1 || useradd --system --home /var/lib/relay --shell /sbin/nologin relay-panel
install -d -o relay-panel -g relay-panel -m 700 /var/lib/relay
chown -R root:root /opt/relay
chmod -R a+rX,go-w /opt/relay
setup_python
/opt/relay/venv/bin/pip install -r /opt/relay/backend/requirements.txt
chmod -R a+rX,go-w /opt/relay/venv
SB_VERSION="$SB_VERSION" RELAY_BUILD_ARCH="$arch" RELAY_PYTHON=/opt/relay/venv/bin/python RELAY_REPO="$RELAY_REPO" bash /opt/relay/scripts/install-kernel.sh
# Node defaults match sb.sh: Bing self-signed certificate, VMess WS without TLS.
self_signed=false
if [[ -n $TLS_CERT ]]; then
  install -m 644 "$TLS_CERT" /etc/relay/node-cert.pem
  install -m 600 "$TLS_KEY" /etc/relay/node-key.pem
else
  self_signed=true
  openssl ecparam -genkey -name prime256v1 -out /etc/relay/node-key.pem
  openssl req -new -x509 -days 36500 -key /etc/relay/node-key.pem -out /etc/relay/node-cert.pem -subj "/CN=$TLS_SERVER_NAME"
fi
# Only a successfully issued/trusted website certificate permits panel startup.
source /opt/relay/scripts/web-certificate.sh
prepare_web_certificate
cert_pub="$(openssl x509 -in /etc/relay/node-cert.pem -pubkey -noout)"
key_pub="$(openssl pkey -in /etc/relay/node-key.pem -pubout)"
[[ $cert_pub == "$key_pub" ]] || { echo '节点证书与私钥不匹配'; exit 1; }
export TLS_SERVER_NAME REALITY_SNI REALITY_HANDSHAKE_HOST REALITY_HANDSHAKE_PORT VMESS_TLS VMESS_WS_PATH TUIC_CONGESTION_CONTROL
# Password goes through stdin, never argv, environment, or an on-disk plaintext file.
printf '%s' "$admin_password" | ADMIN_USER="$ADMIN_USER" PUBLIC_HOST="$PUBLIC_HOST" SELF_SIGNED="$self_signed" VMESS_PORT="$VMESS_PORT" TUIC_PORT="$TUIC_PORT" VLESS_PORT="$VLESS_PORT" HYSTERIA2_PORT="$HYSTERIA2_PORT" ANYTLS_PORT="$ANYTLS_PORT" WEB_PORT="$WEB_PORT" /opt/relay/venv/bin/python /opt/relay/backend/bootstrap.py
unset admin_password
chown -R relay-panel:relay-panel /var/lib/relay
chown root:relay-panel /etc/relay/settings.json
chmod 640 /etc/relay/settings.json
cat > /etc/systemd/system/relay-sing-box.service <<'UNIT'
[Unit]
Description=Relay sing-box
After=network-online.target
Wants=network-online.target
[Service]
User=root
ExecStart=/opt/relay/bin/sing-box run -c /etc/relay/sing-box.json
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576
ProtectHome=true
PrivateTmp=true
ProtectSystem=full
ReadWriteDirectories=/var/lib/relay
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/relay-panel.service <<'UNIT'
[Unit]
Description=Relay management API
After=network-online.target
Wants=network-online.target
[Service]
User=relay-panel
Group=relay-panel
WorkingDirectory=/opt/relay
ExecStart=/opt/relay/venv/bin/python /opt/relay/backend/app.py serve
Restart=on-failure
RestartSec=5
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWriteDirectories=/var/lib/relay /etc/relay /run/lock
# sudo is restricted to the fixed-path config helper; its code/settings remain root-owned.
[Install]
WantedBy=multi-user.target
UNIT
printf '%s\n' 'relay-panel ALL=(root) NOPASSWD: /opt/relay/venv/bin/python /opt/relay/backend/apply.py' > /etc/sudoers.d/relay-panel
chmod 440 /etc/sudoers.d/relay-panel
visudo -cf /etc/sudoers.d/relay-panel
write_relay_nginx final
configure_selinux
nginx -t
systemctl daemon-reload
systemctl enable relay-sing-box relay-panel nginx
systemctl start relay-panel
systemctl reload nginx || systemctl start nginx
sleep 2
curl --fail --silent "http://127.0.0.1:$API_PORT$ADMIN_PATH/api/health" >/dev/null
curl --fail --silent --show-error --resolve "$PUBLIC_HOST:$WEB_PORT:127.0.0.1" "https://$PUBLIC_HOST:$WEB_PORT$ADMIN_PATH/api/health" >/dev/null
configure_firewall
printf '\n安装完成：https://%s:%s%s/\n' "$PUBLIC_HOST" "$WEB_PORT" "$ADMIN_PATH"
echo '请在云安全组放行网站TCP与协议对应TCP/UDP端口；安装器不会清空现有防火墙。'
echo '网站仅通过 HTTPS 与所设路径访问；80 端口只处理证书验证。'
if [[ -z $WEB_TLS_CERT ]]; then echo '网站证书由 relay-acme.timer 自动续期。'; fi
