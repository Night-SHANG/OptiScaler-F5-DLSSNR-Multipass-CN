"""Identity contracts for the pinned F5 derivative, not the inherited PreSR fork."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from f5_upstream_contract import load_contract, validate_config

PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'


class F5ForkContractTests(unittest.TestCase):
    def test_upstream_identity_is_pinned_f5(self):
        cfg = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
        contract = load_contract(ROOT / 'upstream-contract.json')
        validate_config(cfg, contract)
        self.assertEqual(cfg['repository'], 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git')
        self.assertEqual(cfg['branch'], 'main')
        self.assertRegex(cfg['commit'], r'^[0-9a-f]{40}$')
        self.assertEqual(contract['baseline_commit'], PIN)
        validate_config({**cfg, 'commit': PIN, 'upstream_version': 'v0.1.32'}, contract)
        self.assertEqual(cfg['package_prefix'], 'OptiScaler-F5-DLSSNR-Multipass-CN')

    def test_identity_is_explained_in_every_primary_reference(self):
        for name in ('README.md', 'README.zh-CN.md', 'UPSTREAM.md', 'TRANSLATION.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            with self.subTest(name=name):
                self.assertIn(PIN, text)
                self.assertIn('v0.1.32', text)

    def test_legacy_automatic_release_tools_are_not_retained(self):
        for name in ('tools/release_notes.py', 'tools/upstream_status.py',
                     '.github/workflows/release.yml'):
            with self.subTest(name=name):
                self.assertFalse((ROOT / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
