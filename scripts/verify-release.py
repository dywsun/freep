#!/usr/bin/env python3
"""Verify a downloaded release asset against GitHub's SHA256 asset digest."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys


def verify(metadata, asset_path, asset_name):
    matches = [a for a in metadata.get('assets', []) if a.get('name') == asset_name]
    if len(matches) != 1:
        raise ValueError('发布记录中未找到唯一匹配的内核文件')
    digest = matches[0].get('digest') or ''
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('发布记录缺少有效 SHA256，拒绝跳过校验')
    actual = hashlib.sha256()
    with Path(asset_path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            actual.update(chunk)
    if not hmac.compare_digest(actual.hexdigest(), digest.split(':', 1)[1]):
        raise ValueError('内核文件 SHA256 不匹配，停止安装')
    return actual.hexdigest()


if __name__ == '__main__':
    try:
        metadata = json.loads(Path(sys.argv[1]).read_text())
        result = verify(metadata, sys.argv[2], sys.argv[3])
        print('内核 SHA256 校验通过：' + result)
    except (ValueError, OSError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
