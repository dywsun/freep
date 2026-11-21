from pathlib import Path
import unittest

class InstallerTests(unittest.TestCase):
    def test_sensitive_initialization_order_and_port_defaults(self):
        text=(Path(__file__).resolve().parents[1]/'install.sh').read_text()
        self.assertLess(text.index('设置管理员账号'),text.index('install_os_packages'))
        self.assertIn('VMESS_PORT="${VMESS_PORT:-8880}"',text)
        self.assertIn('TUIC_PORT="${TUIC_PORT:-32786}"',text)
        self.assertNotIn('iptables -F',text)
        self.assertNotIn('ufw disable',text)

    def test_domain_prompt_and_certificate_fail_closed(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/'install.sh').read_text()
        self.assertIn('PUBLIC_HOST="${PUBLIC_HOST:-free.dywsun.dpdns.org}"',text)
        self.assertLess(text.index('设置后台访问路径'),text.index('install_os_packages'))
        self.assertLess(text.index('prepare_web_certificate'),text.index('backend/bootstrap.py'))
        self.assertNotIn('keyout /etc/relay/web-key.pem',text)
        acme=(root/'scripts/web-certificate.sh').read_text()
        self.assertIn('--server letsencrypt',acme)
        self.assertIn('location', (root/'backend/web.py').read_text())
        self.assertIn('relay-acme.timer',acme)
        deploy=(root/'scripts/deploy-web-cert.sh').read_text()
        self.assertIn('-verify_hostname',deploy)
        self.assertNotIn('node-key.pem',deploy)

    def test_default_repository_resolves_branch_to_commit(self):
        text=(Path(__file__).resolve().parents[1]/'install.sh').read_text()
        self.assertIn('RELAY_REPO="${RELAY_REPO:-dywsun/freep}"',text)
        self.assertIn('RELAY_REF="${RELAY_REF:-main}"',text)
        self.assertIn('Accept: application/vnd.github.sha',text)
        self.assertLess(text.index('GitHub 返回的提交编号无效'),text.index('archive/$RELAY_REF.tar.gz'))
