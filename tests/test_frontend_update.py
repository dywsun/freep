import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from assets import current_frontend,frontend_asset
spec=importlib.util.spec_from_file_location('updater',Path(__file__).resolve().parents[1]/'scripts/update_frontend.py');updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)

class FrontendUpdateTests(unittest.TestCase):
    def archive(self,path,api=2,malicious=False):
        with tarfile.open(path,'w:gz') as archive:
            for name in updater.REQUIRED:
                content=json.dumps({'api_version':api}).encode() if name=='manifest.json' else b'/* test bundle */' if name.endswith('.js') else b'test'
                entry=tarfile.TarInfo('repo/frontend/'+name);entry.size=len(content);archive.addfile(entry,io.BytesIO(content))
            if malicious:
                entry=tarfile.TarInfo('repo/frontend/../../escape');entry.size=1;archive.addfile(entry,io.BytesIO(b'x'))
    def test_atomic_switch_and_old_assets_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'bundle.tar.gz';self.archive(archive)
            updater.install_archive(root,archive,'a'*40,2)
            self.assertEqual(current_frontend(root)[1],'a'*40)
            updater.install_archive(root,archive,'b'*40,2)
            self.assertEqual(current_frontend(root)[1],'b'*40)
            self.assertTrue(frontend_asset(root,'a'*40,'app.js').is_file())
            updater.switch(root,root/'web-releases'/('a'*40));self.assertEqual(current_frontend(root)[1],'a'*40)
    def test_failure_keeps_previous_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'bundle.tar.gz';self.archive(archive);updater.install_archive(root,archive,'a'*40,2)
            self.archive(archive,api=3)
            with self.assertRaises(ValueError):updater.install_archive(root,archive,'b'*40,2)
            self.assertEqual(current_frontend(root)[1],'a'*40)
            self.archive(archive,malicious=True)
            with self.assertRaises(ValueError):updater.install_archive(root,archive,'c'*40,2)
            self.assertFalse((root/'escape').exists());self.assertEqual(current_frontend(root)[1],'a'*40)

    def test_releases_readable_under_installer_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);archive=root/'bundle.tar.gz';self.archive(archive)
            previous=os.umask(0o077)
            try:updater.install_archive(root,archive,'a'*40,2)
            finally:os.umask(previous)
            self.assertEqual((root/'web-releases').stat().st_mode & 0o777,0o755)
            release=current_frontend(root)[0]
            self.assertEqual(release.stat().st_mode & 0o777,0o755)
            self.assertEqual((release/'index.html').stat().st_mode & 0o777,0o644)
