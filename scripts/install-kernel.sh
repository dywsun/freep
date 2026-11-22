#!/usr/bin/env bash
# Prebuilt statistics kernel first; verified source build is the fallback.
set -Eeuo pipefail
: "${SB_VERSION:?}" "${RELAY_BUILD_ARCH:?}"
[[ $SB_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
[[ $RELAY_BUILD_ARCH == amd64 || $RELAY_BUILD_ARCH == arm64 ]] || exit 1
kernel_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELAY_KERNEL_BIN="${RELAY_KERNEL_BIN:-/opt/relay/bin/sing-box}"
RELAY_PYTHON="${RELAY_PYTHON:-python3}"
RELAY_KERNEL_MODE="${RELAY_KERNEL_MODE:-auto}"
RELAY_KERNEL_REPO="${RELAY_KERNEL_REPO:-${RELAY_REPO:-dywsun/freep}}"
[[ $RELAY_KERNEL_REPO =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || exit 1
[[ $RELAY_KERNEL_MODE =~ ^(auto|prebuilt|source)$ ]] || { echo 'RELAY_KERNEL_MODE 需要 auto / prebuilt / source'; exit 1; }
valid_kernel() {
  local description
  description="$("$1" version 2>/dev/null)" || return 1
  [[ $(sed -n '1s/^sing-box version //p' <<<"$description") == "$SB_VERSION" ]] || return 1
  for feature in with_v2ray_api with_quic with_utls; do
    [[ $description == *"$feature"* ]] || return 1
  done
}
if [[ $RELAY_KERNEL_MODE != source ]] && [[ -x $RELAY_KERNEL_BIN ]] && valid_kernel "$RELAY_KERNEL_BIN"; then
  echo "复用本机 sing-box $SB_VERSION 统计内核，无需下载或编译。"
  exit 0
fi
kernel_tmp="$(mktemp -d)"
trap 'rm -rf -- "$kernel_tmp"' EXIT
if [[ $RELAY_KERNEL_MODE != source ]]; then
  tag="sb-stat-v$SB_VERSION-go1.26.10-r1"
  asset="sing-box-$SB_VERSION-linux-$RELAY_BUILD_ARCH-stat"
  echo "尝试下载预编译统计内核：$RELAY_KERNEL_REPO / $tag / $RELAY_BUILD_ARCH"
  code="$(curl --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 10 --max-time 45 -w '%{http_code}' -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$RELAY_KERNEL_REPO/releases/tags/$tag" -o "$kernel_tmp/release.json")" || code=000
  if [[ $code == 200 ]]; then
    # Select only an exact asset name. A published but incomplete release is an error, not a reason to skip integrity checks.
    "$RELAY_PYTHON" - "$kernel_tmp/release.json" "$asset" <<'PY'
import json,sys
metadata=json.load(open(sys.argv[1]))
assert not metadata.get('draft') and not metadata.get('prerelease'), 'Kernel release is not final'
assert len([a for a in metadata.get('assets',[]) if a.get('name')==sys.argv[2]])==1, 'Kernel asset missing or ambiguous'
PY
    curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 --retry 2 "https://github.com/$RELAY_KERNEL_REPO/releases/download/$tag/$asset" -o "$kernel_tmp/sing-box"
    "$RELAY_PYTHON" "$kernel_dir/verify-release.py" "$kernel_tmp/release.json" "$kernel_tmp/sing-box" "$asset"
    chmod 755 "$kernel_tmp/sing-box"
    valid_kernel "$kernel_tmp/sing-box" || { echo '预编译内核版本、架构或功能不匹配，停止安装。'; exit 1; }
    install -m 755 "$kernel_tmp/sing-box" "$RELAY_KERNEL_BIN"
    echo '预编译统计内核安装完成，已跳过 Go 下载和本机编译。'
    exit 0
  fi
  if [[ $RELAY_KERNEL_MODE == prebuilt ]]; then
    echo "预编译内核不可用（HTTP ${code}），已禁止回退编译。请先在 GitHub Actions 构建发布。"; exit 1
  fi
  echo "预编译版本暂不可用（HTTP ${code}）；回退为本机编译。首次发布完成后，新机器将直接下载。"
fi
SB_VERSION="$SB_VERSION" RELAY_BUILD_ARCH="$RELAY_BUILD_ARCH" RELAY_PYTHON="$RELAY_PYTHON" RELAY_BUILD_OUTPUT="$RELAY_KERNEL_BIN" bash "$kernel_dir/build-sing-box.sh"
valid_kernel "$RELAY_KERNEL_BIN" || { echo '本机编译内核校验失败'; exit 1; }
