#!/usr/bin/env python3
"""Fixed-path privileged helper. The only sudo command granted to relay-panel."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from model import server_config


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)


def main():
    if os.geteuid() != 0: raise SystemExit('root required')
    with open('/run/lock/relay-apply.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        settings = json.loads(Path('/etc/relay/settings.json').read_text())
        fd = os.open('/var/lib/relay/pending.json', os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source: pending = json.loads(source.read(1_000_001))
        state, usage = pending['state'], pending['usage']
        assert isinstance(usage, dict) and all(type(v) in (int, float) and v >= 0 for v in usage.values())
        config = server_config(state, settings, usage)
        target = Path('/etc/relay/sing-box.json')
        staging = Path('/etc/relay/sing-box.next.json')
        data = json.dumps(config).encode()
        staging.write_bytes(data); staging.chmod(0o640)
        run(['/opt/relay/bin/sing-box', 'check', '-c', str(staging)])
        previous = target.read_bytes() if target.exists() else None
        os.replace(staging, target)
        try:
            run(['systemctl', 'restart', 'relay-sing-box'])
            time.sleep(1)
            run(['systemctl', 'is-active', '--quiet', 'relay-sing-box'])
        except Exception:
            if previous is not None:
                target.write_bytes(previous); target.chmod(0o640)
                run(['systemctl', 'restart', 'relay-sing-box'])
            raise
        # InvocationID catches manual restarts too (collector also reads the live ID).
        invocation = run(['systemctl', 'show', '-p', 'ExecMainStartTimestampMonotonic', 'relay-sing-box']).stdout.partition('=')[2].strip()
        Path('/etc/relay/generation').write_text(invocation or secrets.token_hex(16))
        Path('/etc/relay/generation').chmod(0o644)

if __name__ == '__main__':
    try: main()
    except Exception:
        print('Configuration validation/start failed; inspect journalctl -u relay-sing-box', file=sys.stderr)
        raise SystemExit(1)
