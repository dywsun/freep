#!/usr/bin/env bash
# ACME deploy hook. Runs as root, with fixed paths; never touches node certificates.
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || exit 1
read -r domain < /etc/relay/web-domain
[[ $domain =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || exit 1
incoming=/etc/relay/acme-deploy
openssl x509 -in "$incoming/fullchain.pem" -checkend 86400 -noout
# Validate issuer chain and hostname against OS trust roots before enabling HTTPS.
openssl verify -purpose sslserver -verify_hostname "$domain" -untrusted "$incoming/fullchain.pem" "$incoming/fullchain.pem"
cert_pub="$(openssl x509 -in "$incoming/fullchain.pem" -pubkey -noout)"
key_pub="$(openssl pkey -in "$incoming/key.pem" -pubout)"
[[ $cert_pub == "$key_pub" ]] || { echo '网站证书与私钥不匹配'; exit 1; }
backup="$(mktemp -d /etc/relay/cert-backup.XXXXXX)"
trap 'rm -rf -- "$backup"' EXIT
had_previous=false
if [[ -f /etc/relay/web-cert.pem && -f /etc/relay/web-key.pem ]]; then
  had_previous=true
  cp /etc/relay/web-cert.pem "$backup/cert.pem"
  cp /etc/relay/web-key.pem "$backup/key.pem"
fi
install -m 644 "$incoming/fullchain.pem" /etc/relay/web-cert.next.pem
install -m 600 "$incoming/key.pem" /etc/relay/web-key.next.pem
mv /etc/relay/web-cert.next.pem /etc/relay/web-cert.pem
mv /etc/relay/web-key.next.pem /etc/relay/web-key.pem
if command -v restorecon >/dev/null; then restorecon /etc/relay/web-cert.pem /etc/relay/web-key.pem; fi
if ! nginx -t || ! systemctl reload nginx; then
  if [[ $had_previous == true ]]; then
    install -m 644 "$backup/cert.pem" /etc/relay/web-cert.pem
    install -m 600 "$backup/key.pem" /etc/relay/web-key.pem
    if command -v restorecon >/dev/null; then restorecon /etc/relay/web-cert.pem /etc/relay/web-key.pem; fi
    nginx -t && systemctl reload nginx
  else
    rm -f /etc/relay/web-cert.pem /etc/relay/web-key.pem
  fi
  echo '网站证书部署失败，已尝试恢复原证书' >&2
  exit 1
fi
