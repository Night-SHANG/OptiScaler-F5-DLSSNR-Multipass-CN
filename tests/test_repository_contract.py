"""Documentation and repository boundaries; Windows execution is tested separately."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'README.zh-CN.md', 'UPSTREAM.md', 'TRANSLATION.md', 'CONTRIBUTING.md')


class RepositoryContractTests(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_required_f5_files_exist(self):
        required = (*DOCS, 'LICENSE', 'upstream.json', 'Localization/master/catalog.json',
                    'Localization/master/en-US.json', 'Localization/zh-CN.json',
                    'Localization/OptiScalerCN.ini', 'Localization/glossary.json',
                    'Localization/scanner-rules.json', '.github/workflows/build.yml',
                    'tools/localize_f5.py', 'tools/prepare_tree.py', 'tools/package.ps1')
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_document_relative_links_resolve(self):
        for doc in DOCS:
            for target in re.findall(r'\]\(([^)]+)\)', self.read(doc)):
                if '://' in target or target.startswith('#'):
                    continue
                relative = target.split('#', 1)[0]
                with self.subTest(doc=doc, target=target):
                    self.assertTrue((ROOT / relative).exists(), target)

    def test_installation_distinguishes_forwarder_runtime_and_unverified_gpu(self):
        text = self.read('README.zh-CN.md')
        for token in ('nvngx.dll_dlssnr.dll', 'nvngx_dlssnr.dll', 'downloader-only',
                      'GPU', '尚未验收', 'get_streamline.ps1', 'FontPath', 'Language=en-US',
                      'build-metadata.json', 'SHA256SUMS.txt', '不创建 GitHub Release'):
            self.assertIn(token, text)

    def test_provenance_and_non_human_review_are_explicit(self):
        sources = self.read('UPSTREAM.md') + self.read('TRANSLATION.md')
        for token in ('6de9e17a2c49996f2ea888d278c7f034780bd1a7', 'GNU GPL version 3',
                      'Licenses/HybridSource/', 'machine_translated'):
            self.assertIn(token, sources)
        translation = self.read('TRANSLATION.md')
        for token in ('ImHashStr', 'PushID', '配置', '原文', '人工', '不能证明'):
            self.assertIn(token, translation)

    def test_documented_scan_matches_active_workflow(self):
        workflow = self.read('.github/workflows/build.yml')
        scan = 'python tools/scan_ui.py --source _upstream --channel master --upstream-ref v0.1.32 --update --report reports/build-scan.md'
        self.assertIn(scan, workflow)
        for doc in ('README.zh-CN.md', 'CONTRIBUTING.md'):
            self.assertIn(scan, self.read(doc))
        self.assertIn('python tools/localize_f5.py --source _upstream --channel master', workflow)
        self.assertIn('portable-contracts', self.read('README.zh-CN.md'))

    def test_workflows_do_not_embed_translation_secrets_or_publish_releases(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            text = path.read_text(encoding='utf-8')
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r'(?i)sk-[A-Za-z0-9_-]{16,}')
                self.assertNotRegex(text, r'(?i)TRANSLATION_API_KEY\s*:\s*["\']?[A-Za-z0-9_-]{20,}')
                self.assertNotIn('gh release', text)
                self.assertNotIn('action-gh-release', text)
                self.assertNotIn('contents: write', text)


if __name__ == '__main__':
    unittest.main()
