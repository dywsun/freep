import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ChallengeProbeTests(unittest.TestCase):
    def probe(self,failures=0,wrong=False,scope='local'):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);curl=d/'curl'
            curl.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
p=Path(os.environ['COUNT']);n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1))
Path(os.environ['ARGS']).write_text(' '.join(sys.argv[1:]))
if n<int(os.environ['FAILURES']):print('Not found\\n404',end='')
else:print(('wrong' if os.environ['WRONG']=='1' else 'challenge-token')+'\\n200',end='')
''');curl.chmod(0o755);(d/'sleep').write_text('#!/bin/sh\nexit 0\n');(d/'sleep').chmod(0o755)
            env={**os.environ,'PATH':str(d)+os.pathsep+os.environ['PATH'],'COUNT':str(d/'count'),'ARGS':str(d/'args'),'FAILURES':str(failures),'WRONG':'1' if wrong else '0'}
            result=subprocess.run(['bash','-c','set -euo pipefail; source "$1"; PUBLIC_HOST=free.example.com; wait_relay_challenge "$2" example-probe challenge-token','bash',str(ROOT/'scripts/web-certificate.sh'),scope],env=env,capture_output=True,text=True)
            return result,int((d/'count').read_text()),(d/'args').read_text()
    def test_reload_transient_404_is_retried(self):
        r,count,args=self.probe(failures=2);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(count,3);self.assertIn('--resolve free.example.com:80:127.0.0.1',args)
    def test_public_request_is_not_forced_to_loopback(self):
        r,_,args=self.probe(scope='public');self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('--resolve',args);self.assertIn('--noproxy *',args)
    def test_permanent_404_fails_closed(self):
        r,count,_=self.probe(failures=100);self.assertNotEqual(r.returncode,0);self.assertEqual(count,10)
    def test_200_with_wrong_body_never_passes(self):
        r,count,_=self.probe(wrong=True);self.assertNotEqual(r.returncode,0);self.assertEqual(count,10)
