"""Exercise installer decisions without network, Go builds or real kernel execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class KernelInstallTests(unittest.TestCase):
    def run_case(self,code='200',tamper=False,mode='auto',existing=False):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);tools=d/'tools';tools.mkdir();scripts=d/'scripts';scripts.mkdir()
            for name in ['install-kernel.sh','verify-release.py']:(scripts/name).write_bytes((ROOT/'scripts'/name).read_bytes())
            binary=b'#!/bin/sh\nprintf "sing-box version 1.14.4\\nTags: with_quic,with_utls,with_v2ray_api\\n"\n'
            asset=d/'download';asset.write_bytes(binary)
            meta=d/'meta.json';meta.write_text(json.dumps({'assets':[{'name':'sing-box-1.14.4-linux-amd64-stat','digest':'sha256:'+('0'*64 if tamper else hashlib.sha256(binary).hexdigest())}]}))
            (tools/'curl').write_text('''#!/usr/bin/env python3
import os,sys,shutil
args=sys.argv[1:];target=args[args.index('-o')+1]
if '-w' in args:
 shutil.copyfile(os.environ['META'],target);print(os.environ['CODE'],end='')
else:shutil.copyfile(os.environ['ASSET'],target)
''');(tools/'curl').chmod(0o755)
            (scripts/'build-sing-box.sh').write_text('#!/bin/sh\ncp "$ASSET" "$RELAY_BUILD_OUTPUT"\nchmod 755 "$RELAY_BUILD_OUTPUT"\nprintf built > "$MARKER"\n')
            output=d/'kernel';marker=d/'built'
            if existing:output.write_bytes(binary);output.chmod(0o755)
            env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH'],'META':str(meta),'ASSET':str(asset),'CODE':code,'MARKER':str(marker),'SB_VERSION':'1.14.4','RELAY_BUILD_ARCH':'amd64','RELAY_KERNEL_BIN':str(output),'RELAY_KERNEL_MODE':mode}
            result=subprocess.run(['bash',str(scripts/'install-kernel.sh')],env=env,capture_output=True,text=True)
            return result,output.exists(),marker.exists()
    def test_prebuilt_skips_build(self):
        result,installed,built=self.run_case();self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(installed);self.assertFalse(built)
    def test_absent_release_falls_back(self):
        result,installed,built=self.run_case(code='404');self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(installed);self.assertTrue(built)
    def test_bad_digest_fails_closed(self):
        result,installed,built=self.run_case(tamper=True);self.assertNotEqual(result.returncode,0);self.assertFalse(installed);self.assertFalse(built)
    def test_prebuilt_only_does_not_compile(self):
        result,installed,built=self.run_case(code='404',mode='prebuilt');self.assertNotEqual(result.returncode,0);self.assertFalse(installed);self.assertFalse(built)
    def test_reuse_and_force_build(self):
        result,_,built=self.run_case(existing=True);self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(built)
        result,_,built=self.run_case(existing=True,mode='source');self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(built)
