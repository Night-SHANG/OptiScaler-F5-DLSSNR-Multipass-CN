"""Offline tests for continuous F5 synchronization; no external mutation."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
REPO = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'
PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
CN = '6c9128d67a8fb5a21303fabb8affd032806ab862'


class SyncPipelineTests(unittest.TestCase):
    def module(self):
        self.assertTrue((ROOT / 'tools/f5_sync.py').is_file(), 'Safe F5 sync implementation is required')
        return importlib.import_module('f5_sync')

    def cfg(self):
        return {'repository': REPO, 'branch': 'main', 'commit': PIN, 'upstream_version': 'v0.1.32'}

    def test_same_upstream_is_an_exact_noop_candidate(self):
        m = self.module()
        result = m.resolve_candidate(self.cfg(), PIN, 'v0.1.32', PIN, 'identical')
        self.assertEqual(result, self.cfg())

    def test_new_head_uses_exact_release_version_only_when_tag_matches(self):
        m = self.module()
        sha = 'a' * 40
        result = m.resolve_candidate(self.cfg(), sha, 'v0.1.33', sha, 'ahead')
        self.assertEqual(result['commit'], sha)
        self.assertEqual(result['upstream_version'], 'v0.1.33')
        result = m.resolve_candidate(self.cfg(), sha, 'v0.1.32', PIN, 'ahead')
        self.assertEqual(result['upstream_version'], 'main-' + sha[:12])

    def test_floating_invalid_rollback_divergent_and_injected_refs_are_rejected(self):
        m = self.module()
        for sha, state in [('main', 'ahead'), ('a'*39, 'ahead'), ('a'*40, 'behind'),
                           ('a'*40, 'diverged'), ('a'*40, 'identical'), (PIN, 'ahead')]:
            with self.subTest(sha=sha, state=state), self.assertRaises(ValueError):
                m.resolve_candidate(self.cfg(), sha, '', '', state)
        with self.assertRaises(ValueError):
            m.resolve_candidate({**self.cfg(), 'repository': 'https://example.com/evil'}, PIN, '', '', 'identical')
        with self.assertRaises(ValueError):
            m.resolve_candidate(self.cfg(), 'a'*40, 'v1.2.3;touch bad', 'a'*40, 'ahead')

    def test_identity_is_order_stable_and_sensitive_to_runtime_translation_and_pin(self):
        m = self.module()
        files = {'overlay/a.h': b'code', 'Localization/zh-CN.json': b'{"hello":"Chinese"}'}
        first = m.identity_from_files(self.cfg(), files)
        self.assertRegex(first, r'^[0-9a-f]{64}$')
        self.assertEqual(first, m.identity_from_files(self.cfg(), dict(reversed(list(files.items())))))
        self.assertNotEqual(first, m.identity_from_files(self.cfg(), {**files, 'overlay/a.h': b'changed'}))
        self.assertNotEqual(first, m.identity_from_files({**self.cfg(), 'commit': 'a'*40}, files))

    def test_sync_changes_are_limited_to_data_and_accurate_inventory(self):
        m = self.module()
        m.validate_changed_paths(['upstream.json', 'Localization/master/catalog.json',
                                  'Localization/zh-CN.json', 'reports/coverage-inventory.json'])
        for bad in ['tools/f5_sync.py', '.github/workflows/build.yml', 'README.md',
                    'Localization/../secret', 'Localization/unknown.json', 'LICENSE']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.validate_changed_paths(['upstream.json', bad])

    def test_retained_reasons_are_preserved_and_obsolete_entries_pruned(self):
        m = self.module()
        old = {'upstream_commit': PIN, 'note': 'technical', 'entries': [
            {'key': 'keep', 'source': 'GPU', 'reason': 'API identifier', 'occurrences': []},
            {'key': 'gone', 'source': 'old', 'reason': 'technical', 'occurrences': []}]}
        cat = {'upstream_commit': 'a'*40, 'entries': {
            'keep': {'source': 'GPU', 'obsolete': False, 'occurrences': [{'file': 'new.cpp'}]},
            'gone': {'source': 'old', 'obsolete': True}}}
        zh = {'entries': {'keep': {'text': 'GPU'}}}
        result = m.reconcile_retained(old, cat, zh)
        self.assertEqual(result['upstream_commit'], 'a'*40)
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(result['entries'][0]['reason'], 'API identifier')
        self.assertEqual(result['entries'][0]['occurrences'], [{'file': 'new.cpp'}])
        self.assertEqual(len(old['entries']), 2)
        bad = deepcopy(cat); bad['entries']['keep']['source'] = 'Changed'
        with self.assertRaises(ValueError):
            m.reconcile_retained(old, bad, zh)

    def test_new_untranslated_english_cannot_gain_an_automatic_retention_reason(self):
        m = self.module()
        with self.assertRaises(ValueError):
            m.reconcile_retained({'upstream_commit': PIN, 'entries': []},
                                 {'upstream_commit': PIN, 'entries': {'k': {'source': 'New text'}}},
                                 {'entries': {'k': {'text': 'New text'}}})

    def test_release_match_requires_exact_identity_type_tag_and_target(self):
        m = self.module()
        identity = 'a'*64
        release = {'id': 9, 'draft': False, 'prerelease': True, 'target_commitish': CN,
                   'tag_name': 'cn-test-' + PIN[:12] + '-' + CN[:12],
                   'body': f'<!-- f5-cn-sync:v1 identity={identity} cn_commit={CN} -->'}
        self.assertEqual(m.match_release([release], identity, PIN), release)
        for patch in [{'draft': True}, {'prerelease': False}, {'target_commitish': 'main'},
                      {'tag_name': 'v1.2.3'}, {'body': 'unverified'}]:
            self.assertIsNone(m.match_release([{**release, **patch}], identity, PIN))
        self.assertIsNone(m.match_release([release], 'b'*64, PIN))

    def test_unfinished_or_failed_matching_build_is_not_blindly_redispatched(self):
        m = self.module()
        run = {'head_sha': CN, 'event': 'workflow_dispatch', 'path': '.github/workflows/build.yml',
               'status': 'in_progress', 'conclusion': None, 'id': 1}
        self.assertEqual(m.build_disposition([run], CN), 'pending')
        self.assertEqual(m.build_disposition([{**run, 'status': 'completed', 'conclusion': 'failure'}], CN), 'blocked')
        self.assertEqual(m.build_disposition([{**run, 'head_sha': 'b'*40}], CN), 'dispatch')
        self.assertEqual(m.build_disposition([], CN), 'dispatch')
        self.assertEqual(m.build_disposition([{**run, 'display_title': 'F5 build checks',
            'status': 'completed', 'conclusion': 'success'}], CN), 'dispatch')
        self.assertEqual(m.build_disposition([{**run, 'display_title': 'F5 sync publish '+CN}], CN), 'pending')

    def test_workflow_schedules_fixed_repo_and_keeps_translation_secrets_unconfigured(self):
        path = ROOT / '.github/workflows/upstream-sync.yml'
        self.assertTrue(path.is_file(), 'Scheduled synchronization workflow is required')
        text = path.read_text()
        for token in ['schedule:', 'workflow_dispatch:', 'concurrency:', 'cancel-in-progress: false',
                      'python tools/f5_sync.py', 'contents: write', 'actions: write']:
            self.assertIn(token, text)
        for token in ['secrets.TRANSLATION', 'pull_request_target', 'continue-on-error: true', '--force']:
            self.assertNotIn(token, text)

    def test_dispatch_input_must_match_current_full_commit(self):
        m = self.module()
        m.validate_dispatch({'GITHUB_SHA': CN, 'EXPECTED_CN_SHA': ''})
        m.validate_dispatch({'GITHUB_SHA': CN, 'EXPECTED_CN_SHA': CN})
        for expected in ['main', 'a'*40, CN + ';']:
            with self.assertRaises(ValueError):
                m.validate_dispatch({'GITHUB_SHA': CN, 'EXPECTED_CN_SHA': expected})

    def test_transport_rejects_unapproved_write_methods_and_force(self):
        m = self.module()
        api = m.GitHub('offline-test-placeholder')
        for method, path, body in [
            ('DELETE', '/repos/'+m.REPO+'/releases/1', None),
            ('POST', '/repos/'+m.REPO+'/releases', {}),
            ('PATCH', '/repos/'+m.REPO+'/git/refs/heads/main', {'sha': CN, 'force': True}),
            ('PATCH', '/repos/'+m.REPO+'/git/refs/heads/other', {'sha': CN, 'force': False}),
        ]:
            with self.subTest(method=method, path=path), patch.object(m, 'urlopen') as network:
                with self.assertRaises(ValueError):
                    api.request(method, path, body)
                network.assert_not_called()

    def test_published_asset_and_tag_drift_are_not_deduplicated(self):
        m = self.module()
        names = ['package.zip', 'package.zip.sha256', 'build-metadata.json']
        hashes = {name: str(i+1)*64 for i, name in enumerate(names)}
        manifest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        release = {'target_commitish': CN, 'tag_name': 'test', 'assets': [
            {'name': name, 'digest': 'sha256:'+hashes[name], 'state': 'uploaded', 'size': 10} for name in names],
            'body': f'<!-- f5-cn-test-gate:v1 cn_commit={CN} assets_sha256={manifest} -->'}
        class API:
            def get(self, path):
                return {'object': {'type': 'commit', 'sha': CN}}
        m.verify_published_identity(release, API())
        for change in ['asset', 'tag', 'ownership']:
            bad = deepcopy(release)
            if change == 'asset': bad['assets'][0]['digest'] = 'sha256:'+'f'*64
            if change == 'tag': bad['target_commitish'] = 'a'*40
            if change == 'ownership': bad['body'] = ''
            with self.assertRaises(ValueError):
                m.verify_published_identity(bad, API())

    def test_pagination_retrieves_more_than_one_page(self):
        m = self.module()
        api = m.GitHub('offline-test-placeholder')
        with patch.object(api, 'get', side_effect=[list(range(100)), [100]]) as get:
            self.assertEqual(len(api.pages('/repos/'+m.REPO+'/releases')), 101)
            self.assertTrue(get.call_args.args[0].endswith('page=2'))

    def test_data_commit_is_bounded_nonforce_and_uncertain_ref_is_read_back(self):
        m = self.module()
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                subprocess.run(['git', 'init', '-q', str(root)], check=True)
                (root/'upstream.json').write_text('{"commit":"old"}\n')
                subprocess.run(['git', '-C', td, 'add', 'upstream.json'], check=True)
                subprocess.run(['git', '-C', td, '-c', 'user.name=offline',
                    '-c', 'user.email=offline@example.invalid', 'commit', '-qm', 'fixture'], check=True)
                parent = m.git('rev-parse', 'HEAD', root=root)
                (root/'upstream.json').write_text('{"commit":"new"}\n')
                class API:
                    current = parent
                    writes = []
                    def get(self, path):
                        if '/git/commits/' in path: return {'tree': {'sha': 'b'*40}}
                        return {'object': {'sha': self.current}}
                    def request(self, method, path, body):
                        self.writes.append((method, path, body))
                        if path.endswith('/git/trees'): return {'sha': 'c'*40}
                        if path.endswith('/git/commits'): return {'sha': 'a'*40}
                        self.current = body['sha']
                        if uncertain: raise OSError('response lost')
                        return {}
                api = API(); api.writes = []
                self.assertEqual(m._commit_data(api, root, parent, PIN), 'a'*40)
                self.assertEqual(len(api.writes), 3)
                self.assertEqual(api.writes[0][2]['tree'], [{'path': 'upstream.json',
                    'mode': '100644', 'type': 'blob', 'content': '{"commit":"new"}\n'}])
                self.assertEqual(api.writes[-1][2], {'sha': 'a'*40, 'force': False})
                api.current = 'd'*40; api.writes = []
                with self.assertRaises(ValueError):
                    m._commit_data(api, root, parent, PIN)
                self.assertEqual(api.writes, [])


if __name__ == '__main__':
    unittest.main()
