from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from web import validate_path,nginx_config

class WebTests(unittest.TestCase):
    def test_path_validation(self):
        for path in ['/freedom-network','/my_panel/admin-2']:
            self.assertEqual(validate_path(path),path)
        for path in ['', '/', 'admin', '/foo/', '/foo//bar', '/foo/../bar', '/foo;return 200', '/foo?bar', '/foo%2fbar','/foo\\bar','/中文']:
            with self.assertRaises(ValueError,msg=path):validate_path(path)
    def test_nginx_challenge_never_exposes_panel(self):
        config=nginx_config('free.dywsun.dpdns.org',18898,18090,'/freedom-network',True)
        self.assertIn('listen 80;',config)
        self.assertIn('location / { return 404; }',config)
        self.assertNotIn('proxy_pass',config)
        self.assertNotIn('18898',config)
        self.assertNotIn('ssl_certificate',config)
    def test_https_only_prefix_with_no_path_stripping(self):
        config=nginx_config('free.dywsun.dpdns.org',18898,18090,'/freedom-network')
        self.assertIn('listen 18898 ssl',config)
        self.assertIn('listen 443 ssl;',config)
        self.assertIn('location ^~ /freedom-network/sub/',config)
        self.assertIn('limit_except GET { deny all; }',config)
        self.assertIn('location ^~ /freedom-network/',config)
        self.assertIn('proxy_pass http://127.0.0.1:18090;',config)
        self.assertIn('return 308 /freedom-network/;',config)
        self.assertEqual(config.count('location / { return 404; }'),3)
        self.assertNotIn('proxy_pass http://127.0.0.1:18090/;',config)
