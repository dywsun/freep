#!/usr/bin/env bash
set -Eeuo pipefail
# Installer invokes this only when the official binary lacks user-statistics support.
: "${SB_VERSION:?}" "${RELAY_BUILD_ARCH:?}"
build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT
GO_VERSION="${GO_VERSION:-1.26.10}"
[[ $GO_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
archive="go$GO_VERSION.linux-$RELAY_BUILD_ARCH.tar.gz"
curl --fail --location --proto '=https' --tlsv1.2 'https://go.dev/dl/?mode=json&include=all' -o "$build_dir/go-releases.json"
go_sha="$("${RELAY_PYTHON:-python3}" - "$build_dir/go-releases.json" "$archive" <<'PY'
import json,sys
files=[f for release in json.load(open(sys.argv[1])) for f in release['files'] if f['filename']==sys.argv[2]]
assert len(files)==1, 'Go version/archive not found'
print(files[0]['sha256'])
PY
)"
curl --fail --location --proto '=https' --tlsv1.2 "https://go.dev/dl/$archive" -o "$build_dir/$archive"
printf '%s  %s\n' "$go_sha" "$build_dir/$archive" | sha256sum -c -
tar -xzf "$build_dir/$archive" -C "$build_dir"
curl --fail --location --proto '=https' --tlsv1.2 "https://github.com/SagerNet/sing-box/archive/refs/tags/v$SB_VERSION.tar.gz" -o "$build_dir/source.tar.gz"
tar -xzf "$build_dir/source.tar.gz" -C "$build_dir"
cd "$build_dir/sing-box-$SB_VERSION"
# Only capabilities used by this project; no need for TUN/WARP/Cloudflared.
CGO_ENABLED=0 GOTOOLCHAIN=local GOCACHE="$build_dir/cache" GOMODCACHE="$build_dir/mod" "$build_dir/go/bin/go" build -trimpath -tags 'with_quic,with_utls,with_v2ray_api' -ldflags "-X github.com/sagernet/sing-box/constant.Version=$SB_VERSION" -o "$build_dir/sing-box" ./cmd/sing-box
install -m 755 "$build_dir/sing-box" /opt/relay/bin/sing-box
/opt/relay/bin/sing-box version | grep -q with_v2ray_api
