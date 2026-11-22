"""Versioned frontend files: an open page keeps using its original asset bundle."""
import hashlib
from pathlib import Path
import re

ASSETS={'app.js','live.js','share.js','traffic.js','monitor.js','style.css','vendor/qrcode.js'}
API_VERSION=4


def original_version(root):
    h=hashlib.sha256()
    for name in sorted(ASSETS|{'index.html','manifest.json'}):
        p=Path(root)/'frontend'/name
        if p.is_file():h.update(name.encode());h.update(p.read_bytes())
    return h.hexdigest()[:40]


def current_frontend(root):
    root=Path(root);pointer=root/'web-current'
    if pointer.is_symlink():
        release=pointer.resolve(strict=True)
        if release.parent!=(root/'web-releases').resolve() or not re.fullmatch('[a-f0-9]{40}',release.name):raise ValueError('Invalid frontend pointer')
        return release,release.name
    return root/'frontend',original_version(root)


def frontend_asset(root,version,name):
    if name not in ASSETS or not re.fullmatch('[a-f0-9]{40}',version):raise ValueError('Invalid frontend asset')
    release=Path(root)/'web-releases'/version
    if not release.is_dir():
        if version!=original_version(root):raise FileNotFoundError('Frontend version unavailable')
        release=Path(root)/'frontend'
    if release.is_symlink():raise ValueError('Invalid release directory')
    return release/name
