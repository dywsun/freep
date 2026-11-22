import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('verify_release',Path(__file__).resolve().parents[1]/'scripts/verify-release.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ReleaseTests(unittest.TestCase):
    def test_verify_digest_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            asset=Path(directory)/'core.tar.gz';asset.write_bytes(b'official-core')
            digest=hashlib.sha256(asset.read_bytes()).hexdigest()
            metadata={'assets':[{'name':asset.name,'digest':'sha256:'+digest}]}
            self.assertEqual(module.verify(metadata,asset,asset.name),digest)
            asset.write_bytes(b'tampered')
            with self.assertRaises(ValueError):module.verify(metadata,asset,asset.name)
    def test_no_missing_ambiguous_or_invalid_digest(self):
        for assets in [[],[{'name':'core','digest':None}],[{'name':'core','digest':'sha256:invalid'}],[{'name':'core'},{'name':'core'}]]:
            with self.assertRaises(ValueError):module.verify({'assets':assets},'/unused','core')
    def test_installer_uses_asset_digest_not_nonexistent_checksum_file(self):
        text=(Path(__file__).resolve().parents[1]/'install.sh').read_text()
        self.assertNotIn('checksums.txt',text)
        self.assertIn('scripts/install-kernel.sh',text)
        kernel=(Path(__file__).resolve().parents[1]/'scripts/install-kernel.sh').read_text()
        self.assertIn('releases/tags/$tag',kernel)
        self.assertIn('verify-release.py',kernel)
        self.assertNotIn('checksums.txt',kernel)
