#!/usr/bin/env python3
"""Install/roll back a frontend bundle without restarting any services."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import Request,urlopen

REQUIRED={'index.html','app.js','live.js','share.js','traffic.js','monitor.js','style.css','vendor/qrcode.js','manifest.json'}


def validate_bundle(directory,api_version):
    directory=Path(directory)
    if any(not (directory/name).is_file() for name in REQUIRED):raise ValueError('前端文件不完整')
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest.get('api_version')!=api_version:raise ValueError('前端与已安装后端 API 不兼容，请先完成后端升级')
    for file in directory.rglob('*'):
        if file.is_symlink():raise ValueError('前端包不能包含符号链接')
    node=shutil.which('node')
    if node:
        for name in REQUIRED:
            if name.endswith('.js'):subprocess.run([node,'--check',str(directory/name)],check=True,capture_output=True)


def switch(root,directory):
    root=Path(root);directory=Path(directory).resolve()
    if directory.parent!=(root/'web-releases').resolve() or not re.fullmatch('[a-f0-9]{40}',directory.name):raise ValueError('非法版本目录')
    temporary=root/('.web-current-'+str(os.getpid()))
    try:
        temporary.symlink_to(directory,target_is_directory=True)
        os.replace(temporary,root/'web-current')
    finally:
        if temporary.is_symlink():temporary.unlink()


def install_archive(root,archive,version,api_version):
    if not re.fullmatch('[a-f0-9]{40}',version):raise ValueError('提交编号无效')
    root=Path(root);releases=root/'web-releases';releases.mkdir(mode=0o755,parents=True,exist_ok=True)
    # The installer uses umask 077; the unprivileged panel must traverse this directory.
    releases.chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='.stage-',dir=releases) as stage:
        destination=Path(stage);total=0;count=0
        with tarfile.open(archive,'r:gz') as tar:
            for member in tar:
                parts=Path(member.name).parts
                if len(parts)<3 or parts[1]!='frontend':continue
                relative=Path(*parts[2:])
                if relative.is_absolute() or '..' in relative.parts or not member.isfile():
                    if member.isdir() and '..' not in relative.parts:continue
                    raise ValueError('前端包路径或文件类型无效')
                total+=member.size;count+=1
                if total>50*1024*1024 or count>1000:raise ValueError('前端包超过大小限制')
                target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(member) as src,target.open('wb') as out:shutil.copyfileobj(src,out)
        validate_bundle(destination,api_version)
        for file in destination.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)
        destination.chmod(0o755)
        final=releases/version
        if final.exists():validate_bundle(final,api_version)
        else:os.rename(destination,final)
        switch(root,final)
    return final


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',default='dywsun/freep');parser.add_argument('--ref',default='main');parser.add_argument('--rollback');args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('请使用 root 执行页面更新')
    root=Path('/opt/relay');contract=root/'backend/frontend-api.json'
    if not contract.is_file():raise SystemExit('当前后端尚未支持前端热更新，请先完成支持版本的后端升级')
    api=json.loads(contract.read_text())['version']
    if args.rollback:
        if not re.fullmatch('[a-f0-9]{40}',args.rollback):raise SystemExit('回退版本编号无效')
        target=root/'web-releases'/args.rollback;validate_bundle(target,api);switch(root,target);print('前端已回退：'+args.rollback);return
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',args.repo) or not re.fullmatch(r'[A-Za-z0-9_.-]+',args.ref):raise SystemExit('仓库或版本无效')
    version=args.ref
    if not re.fullmatch('[a-f0-9]{40}',version):
        request=Request(f'https://api.github.com/repos/{args.repo}/commits/{args.ref}',headers={'Accept':'application/vnd.github.sha','User-Agent':'Relay-web-updater'})
        with urlopen(request,timeout=30) as response:version=response.read(1024).decode().strip()
    if not re.fullmatch('[a-f0-9]{40}',version):raise SystemExit('GitHub 提交编号无效')
    with tempfile.TemporaryDirectory(prefix='relay-web-') as temporary:
        archive=Path(temporary)/'source.tar.gz'
        with urlopen(Request(f'https://github.com/{args.repo}/archive/{version}.tar.gz',headers={'User-Agent':'Relay-web-updater'}),timeout=60) as response,archive.open('wb') as out:
            total=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>100*1024*1024:raise ValueError('下载包过大')
                out.write(chunk)
        install_archive(root,archive,version,api)
    print('前端已切换到：'+version+'；未重启后台或 sing-box，浏览器刷新后使用新页面。')

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('页面更新失败，保留当前版本：'+str(exc))
