#!/usr/bin/env bash
# Sourced by install.sh after administrator input. Do not replace system Python.
install_os_packages() {
  local major="${VERSION_ID%%.*}"
  case "$ID" in
    ubuntu|debian)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y --no-install-recommends ca-certificates curl tar openssl python3 python3-venv sudo nginx iproute2
      ;;
    centos)
      if [[ $major == 7 || $major == 8 ]]; then
        [[ $(uname -m) == x86_64 ]] || { echo 'CentOS 7/8 兼容分支仅支持 x86_64'; return 1; }
        echo 'CentOS 7/8 使用独立归档源配置，不覆盖系统 repo，不替换系统 Python。'
        local config=/etc/relay-bootstrap-yum.conf
        cat > "$config" <<'CONF'
[main]
reposdir=/dev/null
gpgcheck=1
sslverify=1
keepcache=0
CONF
        if [[ $major == 7 ]]; then
          cat >> "$config" <<'CONF'
[relay-base]
name=CentOS 7.9 Base archive
baseurl=https://vault.centos.org/7.9.2009/os/$basearch/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
[relay-updates]
name=CentOS 7.9 Updates archive
baseurl=https://vault.centos.org/7.9.2009/updates/$basearch/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
[relay-extras]
name=CentOS 7.9 Extras archive
baseurl=https://vault.centos.org/7.9.2009/extras/$basearch/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-7
[relay-epel]
name=EPEL 7 archive
baseurl=https://archives.fedoraproject.org/pub/archive/epel/7/$basearch/
gpgkey=https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-7
CONF
          yum -c "$config" install -y ca-certificates curl tar openssl sudo nginx iproute policycoreutils-python
        else
          cat >> "$config" <<'CONF'
[relay-base]
name=CentOS 8.5 BaseOS archive
baseurl=https://vault.centos.org/8.5.2111/BaseOS/$basearch/os/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
[relay-appstream]
name=CentOS 8.5 AppStream archive
baseurl=https://vault.centos.org/8.5.2111/AppStream/$basearch/os/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
[relay-extras]
name=CentOS 8.5 Extras archive
baseurl=https://vault.centos.org/8.5.2111/extras/$basearch/os/
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
CONF
          dnf -c "$config" install -y ca-certificates curl tar openssl sudo nginx iproute policycoreutils-python-utils
        fi
      else
        dnf install -y ca-certificates tar openssl python3 python3-pip sudo nginx iproute policycoreutils-python-utils
        command -v curl >/dev/null || dnf install -y curl
      fi
      ;;
    *) echo '不支持该发行版'; return 1;;
  esac
}

setup_python() {
  if command -v python3 >/dev/null && python3 -c 'import sys; assert sys.version_info >= (3,9)' 2>/dev/null; then
    python3 -m venv /opt/relay/venv
  else
    # Static musl uv runs without replacing old glibc or /usr/bin/python.
    local uv_arch=x86_64
    [[ $(uname -m) == aarch64 ]] && uv_arch=aarch64
    local asset="uv-$uv_arch-unknown-linux-musl.tar.gz"
    local release=https://github.com/astral-sh/uv/releases/download/0.13.7
    curl --fail --location --proto '=https' --tlsv1.2 "$release/$asset" -o "$relay_tmp/$asset"
    curl --fail --location --proto '=https' --tlsv1.2 "$release/$asset.sha256" -o "$relay_tmp/uv.sha256"
    local digest
    read -r digest _ < "$relay_tmp/uv.sha256"
    [[ $digest =~ ^[a-f0-9]{64}$ ]] || return 1
    printf '%s  %s\n' "$digest" "$relay_tmp/$asset" | sha256sum -c -
    tar -xzf "$relay_tmp/$asset" -C "$relay_tmp"
    install -m 755 "$relay_tmp/uv-$uv_arch-unknown-linux-musl/uv" /opt/relay/bin/uv
    export UV_PYTHON_INSTALL_DIR=/opt/relay/python UV_CACHE_DIR="$relay_tmp/uv-cache"
    /opt/relay/bin/uv python install 3.12
    /opt/relay/bin/uv venv --python 3.12 --seed /opt/relay/venv
    chmod -R a+rX /opt/relay/python /opt/relay/venv
  fi
}

configure_selinux() {
  if command -v getenforce >/dev/null && [[ $(getenforce) != Disabled ]]; then
    for relay_port in "$WEB_PORT" "$API_PORT"; do
      if ! semanage port -a -t http_port_t -p tcp "$relay_port" 2>/dev/null; then
        # Existing assignment must already be an HTTP port; do not steal another service's label.
        semanage port -l | awk '$1=="http_port_t" && $2=="tcp" {for(i=3;i<=NF;i++) {gsub(",","",$i); print $i}}' | grep -qx "$relay_port" || { echo "SELinux 端口 $relay_port 已有其他类型，请另选端口"; return 1; }
      fi
    done
    setsebool -P httpd_can_network_relay on
    semanage fcontext -a -t httpd_config_t '/etc/relay/web-(cert|key)\.pem' 2>/dev/null || semanage fcontext -m -t httpd_config_t '/etc/relay/web-(cert|key)\.pem'
    semanage fcontext -a -t httpd_sys_content_t '/var/lib/relay-acme(/.*)?' 2>/dev/null || semanage fcontext -m -t httpd_sys_content_t '/var/lib/relay-acme(/.*)?'
    restorecon -R /var/lib/relay-acme
    [[ ! -f /etc/relay/web-cert.pem ]] || restorecon /etc/relay/web-cert.pem
    [[ ! -f /etc/relay/web-key.pem ]] || restorecon /etc/relay/web-key.pem
  fi
  return 0
}

configure_firewall() {
  if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    for relay_port in 80 8443 "$WEB_PORT" "$VMESS_PORT" "$VLESS_PORT" "$ANYTLS_PORT"; do
      firewall-cmd --add-port="$relay_port/tcp"
      firewall-cmd --permanent --add-port="$relay_port/tcp"
    done
    for relay_port in "$TUIC_PORT" "$HYSTERIA2_PORT"; do
      firewall-cmd --add-port="$relay_port/udp"
      firewall-cmd --permanent --add-port="$relay_port/udp"
    done
  elif command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    for relay_port in 80 8443 "$WEB_PORT" "$VMESS_PORT" "$VLESS_PORT" "$ANYTLS_PORT"; do ufw allow "$relay_port/tcp"; done
    for relay_port in "$TUIC_PORT" "$HYSTERIA2_PORT"; do ufw allow "$relay_port/udp"; done
  fi
}
