"""Future sync releases reuse the complete fixed publisher verifier, offline only."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_test_release_gate import PackageFixture, FakeGitHub, SHA, PIN, REPO, TAG, context_data, digest
import publish_test_release as core

NEXT_PIN = 'b' * 40
NEXT_VERSION = 'v0.1.33-rc.1'
SYNC_TAG = 'cn-test-' + NEXT_PIN[:12] + '-' + SHA[:12]
IDENTITY = 'c' * 64


def future_fixture(root, version=NEXT_VERSION):
    fixture = PackageFixture(root)
    for item in fixture.artifacts.iterdir():
        item.unlink()
    fixture.name = 'OptiScaler-F5-DLSSNR-Multipass-CN-' + version + '-cn-' + SHA[:12] + '-' + NEXT_PIN[:12] + '.zip'
    fixture.inner.update(upstream_commit=NEXT_PIN, upstream_version=version, package_version=version + '-cn-' + SHA[:12])
    catalog = json.loads(fixture.catalog.read_text())
    catalog['upstream_commit'] = NEXT_PIN
    fixture.catalog.write_text(json.dumps(catalog))
    fixture.write()
    return fixture


def sync_inputs():
    env, _ = context_data()
    env['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
    event = {'repository': {'full_name': REPO}, 'ref': 'refs/heads/main',
             'inputs': {'sync_publish': 'true', 'expected_sha': SHA}}
    return env, event


class SyncGitHub(FakeGitHub):
    def api(self, method, path, payload=None):
        if method == 'GET' and '/git/matching-refs/tags/' in path:
            return [] if self.tag is None else [{'ref': 'refs/tags/' + SYNC_TAG,
                                                 'object': {'type': 'commit', 'sha': self.tag}}]
        data = super().api(method, path, payload)
        if method == 'GET' and path.endswith('actions/runs/123'):
            data['event'] = 'workflow_dispatch'
        return data


class ParameterizedVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = future_fixture(Path(self.temp.name))

    def package(self):
        return core.verify_artifact(self.fixture.artifacts, SHA, self.fixture.catalog,
                                    upstream=NEXT_PIN, upstream_version=NEXT_VERSION)

    def test_validated_future_identity_uses_all_existing_package_gates(self):
        self.assertEqual(self.package()['metadata']['upstream_commit'], NEXT_PIN)
        self.fixture.write(outer_changes={'upstream_commit': PIN})
        with self.assertRaises(core.GateError):
            self.package()

    def test_default_fixed_publisher_still_rejects_future_package(self):
        with self.assertRaises(core.GateError):
            core.verify_artifact(self.fixture.artifacts, SHA, self.fixture.catalog)

    def test_future_verifier_keeps_inner_manifest_pe_and_installer_gates(self):
        for defect in ('manifest', 'pe', 'installer', 'hybrid', 'license'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                fixture = future_fixture(Path(temp))
                if defect == 'manifest': fixture.write(manifest_changes={'README.md': '0' * 64})
                elif defect == 'pe':
                    fixture.payload['OptiScaler.dll'] = b'not a DLL'
                    fixture.inner['binaries'][0]['sha256'] = digest(b'not a DLL')
                    fixture.write()
                elif defect == 'installer':
                    fixture.payload['setup_windows.bat'] = 'echo 中文但不是验证过的脚本\n'.encode()
                    fixture.write()
                elif defect == 'hybrid':
                    fixture.inner['hybrid_archive_sha256'] = '0' * 64
                    fixture.write()
                else:
                    del fixture.payload['LICENSE']
                    fixture.write()
                with self.assertRaises(core.GateError):
                    core.verify_artifact(fixture.artifacts, SHA, fixture.catalog,
                                         upstream=NEXT_PIN, upstream_version=NEXT_VERSION)

    def test_main_snapshot_version_is_bound_to_upstream_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            version = 'main-' + NEXT_PIN[:12]
            fixture = future_fixture(Path(temp), version)
            self.assertEqual(core.verify_artifact(fixture.artifacts, SHA, fixture.catalog,
                             upstream=NEXT_PIN, upstream_version=version)['metadata']['upstream_version'], version)
            with self.assertRaises(core.GateError):
                core.verify_artifact(fixture.artifacts, SHA, fixture.catalog,
                                     upstream=NEXT_PIN, upstream_version='main-' + 'd' * 12)

    def test_transport_accepts_only_fixed_or_deterministic_test_tags(self):
        for tag in ('latest', 'v1.0.0', SYNC_TAG + '/extra', '--force', 'cn-test-short-short'):
            with self.subTest(tag=tag), self.assertRaises(core.GateError):
                core.GitHub(release_tag=tag)
        transport = core.GitHub(release_tag=SYNC_TAG)
        with patch.object(core.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'{}'
            transport.upload(self.fixture.artifacts / self.fixture.name)
            args = run.call_args.args[0]
            self.assertIn(SYNC_TAG, args)
            self.assertNotIn('--clobber', args)
            with self.assertRaises(core.GateError):
                transport.api('POST', core.API_ROOT + 'releases',
                              {'tag_name': TAG, 'draft': True, 'prerelease': True, 'make_latest': 'false'})


class SyncedPublisherTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'tools/publish_synced_release.py').is_file(),
                        'The narrowly scoped future sync release publisher must exist')
        self.sync = importlib.import_module('publish_synced_release')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = future_fixture(self.root)
        self.env, self.event = sync_inputs()
        self.cfg = json.loads((ROOT / 'upstream.json').read_text())
        self.cfg.update(commit=NEXT_PIN, upstream_version=NEXT_VERSION)
        (self.root / 'upstream.json').write_text(json.dumps(self.cfg))
        shutil.copyfile(ROOT / 'upstream-contract.json', self.root / 'upstream-contract.json')
        loc = self.root / 'Localization'
        (loc / 'master').mkdir(parents=True)
        shutil.copyfile(self.fixture.catalog, loc / 'installers.zh-CN.json')
        source_hash = digest(b'Hello')
        self.catalog = {'channel': 'master', 'upstream_commit': NEXT_PIN,
                        'entries': {'hello': {'source': 'Hello', 'source_hash': source_hash}}}
        self.zh = {'locale': 'zh-CN', 'entries': {'hello': {'text': '你好', 'state': 'machine_translated', 'source_hash': source_hash}}}
        self.retained = {'upstream_commit': NEXT_PIN, 'entries': []}
        self.pending = {'locale': 'zh-CN', 'entries': {}, 'scan': {'added': ['hello'], 'changed': [], 'removed': []}}
        self.write_localization()
        self.block = patch.object(core.subprocess, 'run', side_effect=AssertionError('No external subprocess in offline tests'))
        self.block.start()
        self.addCleanup(self.block.stop)

    def write_localization(self):
        for path, data in [('master/catalog.json', self.catalog), ('zh-CN.json', self.zh),
                           ('retained-English.json', self.retained), ('master/pending.json', self.pending)]:
            (self.root / 'Localization' / path).write_text(json.dumps(data))

    def prepare(self):
        return self.sync.prepare_publication(self.fixture.artifacts, self.env, self.event,
                                              root=self.root, sync_identity=IDENTITY)

    def test_dispatch_context_and_body_bind_exact_commit_coverage_and_identity(self):
        package, context = self.prepare()
        self.assertEqual(context['tag'], SYNC_TAG)
        self.assertEqual(context['event'], 'workflow_dispatch')
        payload = core.release_payload(package, context)
        self.assertEqual(payload['tag_name'], SYNC_TAG)
        self.assertIs(payload['prerelease'], True)
        self.assertEqual(payload['make_latest'], 'false')
        self.assertIn('固定上游 F5 ' + NEXT_VERSION, payload['body'])
        self.assertIn('缺失 0，过期 0', payload['body'])
        self.assertIn('f5-cn-static-catalog-progress:begin', payload['body'])
        self.assertIn('<!-- f5-cn-sync:v1 identity=' + IDENTITY + ' cn_commit=' + SHA + ' -->', payload['body'])
        self.assertIn('GPU/游戏', payload['body'])
        self.assertIn('字体', payload['body'])
        self.assertIn('downloader-only', payload['body'])
        self.assertIn(core.ownership_marker(package, context), payload['body'])

    def test_only_exact_dispatch_inputs_with_successful_results_are_accepted(self):
        original_env, original_event = deepcopy(self.env), deepcopy(self.event)
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_EVENT_NAME', 'push'),
                           ('GITHUB_REF', 'refs/heads/other'), ('GITHUB_REPOSITORY', 'other/repo'),
                           ('GITHUB_SHA', 'd' * 40), ('BUILD_RESULT', 'failure'), ('PORTABLE_RESULT', 'skipped'),
                           ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '0'), ('GH_TOKEN', ''),
                           ('GITHUB_SERVER_URL', 'https://evil.example'), ('GH_HOST', 'evil.example')]:
            self.env = {**original_env, key: value}
            with self.subTest(key=key), self.assertRaises(core.GateError): self.prepare()
        self.env = original_env
        for changes in ({'sync_publish': True}, {'sync_publish': 'false'}, {'expected_sha': 'd' * 40},
                        {'expected_sha': SHA[:12]}, {'expected_sha': SHA.upper()}):
            self.event = {**original_event, 'inputs': {**original_event['inputs'], **changes}}
            with self.subTest(inputs=changes), self.assertRaises(core.GateError): self.prepare()
        for key, value in [('inputs', None), ('repository', {'full_name': 'other/repo'}), ('ref', 'refs/heads/other')]:
            self.event = {**original_event, key: value}
            with self.subTest(key=key), self.assertRaises(core.GateError): self.prepare()

    def test_current_validated_config_is_not_inferred_from_artifact_metadata(self):
        for change in ({'commit': 'd' * 40}, {'repository': 'https://github.com/other/repo.git'},
                       {'branch': 'develop'}, {'commit': 'main'}, {'upstream_version': 'main-000000000000'}):
            (self.root / 'upstream.json').write_text(json.dumps({**self.cfg, **change}))
            with self.subTest(change=change), self.assertRaises((core.GateError, ValueError)):
                self.prepare()

    def test_missing_stale_or_wrong_source_coverage_blocks_before_any_api(self):
        original = deepcopy(self.zh)
        for change in ('missing', 'stale', 'empty', 'wrong-pin'):
            self.zh = deepcopy(original)
            self.catalog['upstream_commit'] = NEXT_PIN
            if change == 'missing': self.zh['entries'].clear()
            if change == 'stale': self.zh['entries']['hello']['source_hash'] = 'd' * 64
            if change == 'empty': self.zh['entries']['hello']['text'] = ''
            if change == 'wrong-pin': self.catalog['upstream_commit'] = PIN
            self.write_localization()
            with self.subTest(change=change), self.assertRaises((core.GateError, ValueError)): self.prepare()

    def test_invalid_sync_identity_and_artifact_path_are_rejected(self):
        for identity in ('', IDENTITY.upper(), 'c' * 63, '<!-- forged -->'):
            with self.subTest(identity=identity), self.assertRaises(core.GateError):
                self.sync.prepare_publication(self.fixture.artifacts, self.env, self.event,
                                              root=self.root, sync_identity=identity)
        with self.assertRaises(core.GateError):
            self.sync.prepare_publication(self.root / 'other', self.env, self.event,
                                          root=self.root, sync_identity=IDENTITY)

    def test_checkout_sha_and_tracked_cleanliness_are_required(self):
        self.block.stop()
        for sha, status, code in ((SHA, '', 0), ('d' * 40, '', 0), (SHA, ' M upstream.json\n', 0), (SHA, '', 1)):
            with self.subTest(sha=sha, status=status, code=code), patch.object(core.subprocess, 'run') as run:
                run.return_value.returncode = code
                run.return_value.stderr = b''
                def results(command, **kwargs):
                    from subprocess import CompletedProcess
                    output = sha + '\n' if 'rev-parse' in command else status
                    return CompletedProcess(command, code, output.encode(), b'')
                run.side_effect = results
                if sha == SHA and not status and not code:
                    self.sync.verify_checkout(self.root, SHA)
                else:
                    with self.assertRaises(core.GateError): self.sync.verify_checkout(self.root, SHA)

    def test_tag_context_cannot_diverge_from_verified_package_identity(self):
        package, context = self.prepare()
        for changes in ({'tag': TAG}, {'tag': 'cn-test-' + 'd' * 12 + '-' + SHA[:12]},
                        {'upstream': 'd' * 40}, {'event': 'push'}, {'upstream_version': 'v0.1.34'}):
            github = SyncGitHub(core, package, context)
            with self.subTest(changes=changes), self.assertRaises(core.GateError):
                core.publish(package, {**context, **changes}, github)
            self.assertEqual(github.mutations, [])

    def test_cli_runs_checkout_preflight_and_uses_sync_scoped_transport(self):
        from subprocess import CompletedProcess
        from types import SimpleNamespace
        event_path = self.root / 'event.json'
        event_path.write_text(json.dumps(self.event))
        package, context = self.prepare()
        github = SyncGitHub(core, package, context)
        def git_result(command, **kwargs):
            return CompletedProcess(command, 0, (SHA + '\n').encode() if 'rev-parse' in command else b'', b'')
        self.block.stop()
        with patch.object(self.sync, 'ROOT', self.root), patch.dict(self.sync.os.environ,
                {**self.env, 'GITHUB_EVENT_PATH': str(event_path)}, clear=True), \
                patch.dict(sys.modules, {'f5_sync': SimpleNamespace(release_identity=lambda root: IDENTITY)}), \
                patch.object(core.subprocess, 'run', side_effect=git_result), \
                patch.object(core, 'GitHub', return_value=github) as transport:
            self.assertEqual(self.sync.main(['--artifact-dir', str(self.fixture.artifacts)]), 0)
            transport.assert_called_once_with(release_tag=SYNC_TAG)
        self.assertIs(github.release['draft'], False)

    def test_sync_release_publishes_only_after_same_run_and_remote_byte_checks(self):
        package, context = self.prepare()
        github = SyncGitHub(core, package, context)
        self.assertEqual(core.publish(package, context, github),
                         f'https://github.com/{REPO}/releases/tag/{SYNC_TAG}')
        self.assertIs(github.release['draft'], False)
        self.assertEqual(github.release['tag_name'], SYNC_TAG)
        self.assertEqual(len(github.assets), 3)
        github.mutations.clear()
        core.publish(package, context, github)
        self.assertEqual(github.mutations, [])

    def test_sync_release_rejects_other_run_event_failed_job_or_main_race(self):
        for defect in ('event', 'sha', 'attempt', 'branch', 'workflow', 'build', 'main', 'late-main'):
            package, context = self.prepare()
            github = SyncGitHub(core, package, context)
            original_api = github.api
            reads = []
            def api(method, path, payload=None):
                data = original_api(method, path, payload)
                if method == 'GET' and path.endswith('actions/runs/123'):
                    for field, value, marker in [('event', 'push', 'event'), ('head_sha', 'd' * 40, 'sha'),
                                                 ('run_attempt', 2, 'attempt'), ('head_branch', 'other', 'branch'),
                                                 ('path', '.github/workflows/other.yml', 'workflow')]:
                        if defect == marker: data[field] = value
                if method == 'GET' and path.endswith('git/ref/heads/main'):
                    reads.append(path)
                    if defect == 'late-main' and len(reads) > 1: data['object']['sha'] = 'd' * 40
                return data
            github.api = api
            if defect == 'build': github.build_result = 'failure'
            if defect == 'main': github.main_sha = 'd' * 40
            with self.subTest(defect=defect), self.assertRaises(core.GateError):
                core.publish(package, context, github)
            self.assertFalse(any(item[0] == 'PATCH' for item in github.mutations))
            if defect != 'late-main': self.assertEqual(github.mutations, [])

    def test_sync_does_not_replace_conflicting_release_assets_or_identity(self):
        for defect in ('tag', 'bytes', 'identity', 'coverage'):
            package, context = self.prepare()
            github = SyncGitHub(core, package, context)
            core.publish(package, context, github)
            github.mutations.clear()
            if defect == 'tag': github.tag = 'd' * 40
            if defect == 'bytes': github.assets['build-metadata.json'] = b'tampered'
            if defect == 'identity': github.release['body'] = github.release['body'].replace(IDENTITY, 'd' * 64)
            if defect == 'coverage': github.release['body'] = github.release['body'].replace('缺失 0', '缺失 1')
            with self.subTest(defect=defect), self.assertRaises(core.GateError):
                core.publish(package, context, github)
            self.assertEqual(github.mutations, [])


if __name__ == '__main__':
    unittest.main()
