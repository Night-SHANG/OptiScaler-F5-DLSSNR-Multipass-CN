"""The release publisher is tested offline; no test authenticates or publishes."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SHA = 'a' * 40
PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
REPO = 'Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN'
TAG = 'v0.1.32-cn-test.1'
TRIGGER = 'release: publish ' + TAG


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pe64():
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', data, 0x84, 0x8664)
    struct.pack_into('<H', data, 0x96, 0x2000)
    struct.pack_into('<H', data, 0x98, 0x20b)
    return bytes(data)


def context_data():
    env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPO,
           'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
           'GITHUB_SHA': SHA, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
           'BUILD_RESULT': 'success', 'PORTABLE_RESULT': 'success', 'GH_TOKEN': 'test-placeholder'}
    event = {'repository': {'full_name': REPO}, 'ref': 'refs/heads/main',
             'after': SHA, 'head_commit': {'id': SHA, 'message': TRIGGER}, 'deleted': False}
    return env, event


class PackageFixture:
    def __init__(self, root):
        self.root = root
        self.artifacts = root / 'release-artifact'
        self.artifacts.mkdir()
        self.catalog = root / 'installers.json'
        self.name = 'OptiScaler-F5-DLSSNR-Multipass-CN-v0.1.32-cn-' + SHA[:12] + '-' + PIN[:12] + '.zip'
        scripts = ['setup_windows.bat', 'setup_linux.sh', 'get_streamline.ps1']
        self.payload = {name: 'echo 中文安装提示\n'.encode() for name in scripts}
        self.payload.update({name: b'license or documentation\n' for name in [
            'LICENSE', 'README.md', 'INSTALL-DLSSNR.md', 'UPSTREAM.CN.md', 'OptiScaler.ini',
            '!! EXTRACT ALL FILES TO GAME FOLDER !!', 'Licenses/HybridSource/LICENSE']})
        self.payload['README.CN.zh-CN.md'] = '中文使用说明\n'.encode()
        self.payload['OptiScalerCN.ini'] = b'[Localization]\nLanguage=zh-CN\nFontPath=\n'
        self.payload['redist/streamline/manifest.json'] = b'{"schema":1}\n'
        records = [{'path': name, 'packaged': True, 'localized_sha256': digest(data)}
                   for name, data in self.payload.items() if name in scripts]
        records.insert(2, {'path': 'Streamlined_fetcher_windows.bat', 'packaged': False,
                           'localized_sha256': 'b' * 64})
        self.catalog.write_text(json.dumps({'schema': 1, 'upstream_commit': PIN, 'scripts': records,
            'redist': {'path': 'redist/streamline/manifest.json',
                       'sha256': digest(self.payload['redist/streamline/manifest.json'])}}))
        hybrid = []
        for i in range(15):
            path = f'asset-{i}.bin'
            data = f'resource {i}'.encode()
            self.payload['OptiScaler/nvfp4/hybrid/' + path] = data
            hybrid.append({'path': path, 'sha256': digest(data)})
        binaries = []
        for name in ['OptiScaler.dll', 'nvngx.dll_dlssnr.dll']:
            self.payload[name] = pe64()
            binaries.append({'name': name, 'sha256': digest(self.payload[name])})
        self.inner = {'schema': 1, 'upstream_repository': 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git',
                      'upstream_commit': PIN, 'upstream_version': 'v0.1.32', 'cn_commit': SHA,
                      'package_version': 'v0.1.32-cn-' + SHA[:12], 'variant': 'downloader-only',
                      'configuration': 'Release', 'platform': 'x64', 'toolset': 'v143',
                      'msbuild_version': '17.0', 'hybrid_assets': hybrid,
                      'hybrid_archive_sha256': '3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037',
                      'recursive_submodules': [' ' + 'b' * 40 + ' external/example (heads/main)'],
                      'binaries': binaries, 'built_at_utc': '2026-10-20T01:00:00Z',
                      'packaged_at_utc': '2026-10-20T01:01:00Z',
                      'game_runtime_validation': 'not performed by this workflow'}
        self.write()

    def write(self, outer_changes=None, manifest_changes=None):
        self.payload['BUILD-INFO.CN.json'] = json.dumps(self.inner).encode('utf-8')
        hashes = {name: digest(data) for name, data in self.payload.items() if name != 'SHA256SUMS.txt'}
        hashes.update(manifest_changes or {})
        self.payload['SHA256SUMS.txt'] = ''.join(f'{value} *{name}\n' for name, value in sorted(hashes.items())).encode()
        with zipfile.ZipFile(self.artifacts / self.name, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.payload.items():
                archive.writestr(name, data)
        sha = digest((self.artifacts / self.name).read_bytes())
        outer = {**self.inner, 'package': self.name, 'sha256': sha, 'verified_archive_files': len(self.payload)}
        outer.update(outer_changes or {})
        (self.artifacts / 'build-metadata.json').write_bytes(b'\xef\xbb\xbf' + json.dumps(outer).encode())
        (self.artifacts / (self.name + '.sha256')).write_text(f'{sha} *{self.name}\n')


class FakeGitHub:
    """In-memory model of just the fixed release endpoints, including lost replies."""
    def __init__(self, gate, package, context):
        self.gate, self.package, self.context = gate, package, context
        self.release = None
        self.tag = None
        self.assets = {}
        self.mutations = []
        self.fail_after = None
        self.bad_download = False
        self.build_result = 'success'
        self.main_sha = SHA

    def api(self, method, path, payload=None):
        prefix = 'repos/' + REPO + '/'
        assert path.startswith(prefix), path
        tail = path[len(prefix):]
        if method == 'GET':
            if tail == 'git/ref/heads/main':
                return {'object': {'type': 'commit', 'sha': self.main_sha}}
            if tail.startswith('git/matching-refs/tags/'):
                return [] if self.tag is None else [{'ref': 'refs/tags/' + TAG, 'object': {'type': 'commit', 'sha': self.tag}}]
            if tail == 'actions/runs/123':
                return {'id': 123, 'event': 'push', 'head_sha': SHA, 'head_branch': 'main',
                        'path': '.github/workflows/build.yml', 'repository': {'full_name': REPO}, 'run_attempt': 1}
            if tail.startswith('actions/runs/123/attempts/1/jobs?'):
                return {'jobs': [{'name': 'build', 'conclusion': self.build_result, 'status': 'completed', 'run_id': 123},
                                 {'name': 'portable-contracts', 'conclusion': 'success', 'status': 'completed', 'run_id': 123}]}
            if tail.startswith('releases?'):
                return [] if self.release is None else [deepcopy(self.release)]
            if tail == 'releases/7':
                return deepcopy(self.release)
            if tail.startswith('releases/7/assets?'):
                return [self.asset_record(name) for name in self.assets]
            raise AssertionError(path)
        self.mutations.append((method, tail, deepcopy(payload)))
        if method == 'POST' and tail == 'releases':
            if self.release is not None:
                raise self.gate.GitHubError('already exists')
            self.release = {**payload, 'id': 7, 'html_url': f'https://github.com/{REPO}/releases/tag/{TAG}'}
            if self.fail_after == 'create':
                self.fail_after = None
                raise self.gate.GitHubError('lost create reply')
            return deepcopy(self.release)
        if method == 'PATCH' and tail == 'releases/7':
            self.release.update(payload)
            self.tag = SHA
            if self.fail_after == 'publish':
                self.fail_after = None
                raise self.gate.GitHubError('lost publish reply')
            return deepcopy(self.release)
        raise AssertionError((method, path))

    def asset_record(self, name):
        return {'id': list(self.assets).index(name) + 1, 'name': name, 'size': len(self.assets[name]),
                'state': 'uploaded', 'digest': 'sha256:' + digest(self.assets[name])}

    def upload(self, path):
        assert path.name not in self.assets, 'overwrite attempt'
        self.mutations.append(('UPLOAD', path.name, None))
        self.assets[path.name] = path.read_bytes()
        if self.fail_after == 'upload':
            self.fail_after = None
            raise self.gate.GitHubError('lost upload reply')

    def download(self, asset_id, target):
        name = list(self.assets)[asset_id - 1]
        target.write_bytes(b'corruption' if self.bad_download else self.assets[name])


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'tools/publish_test_release.py').is_file(),
                        'A narrowly scoped test release publisher must exist')
        self.gate = importlib.import_module('publish_test_release')
        self.block = patch.object(self.gate.subprocess, 'run', side_effect=AssertionError('External subprocess prohibited in tests'))
        self.block.start()
        self.addCleanup(self.block.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = PackageFixture(Path(self.temp.name))
        self.env, self.event = context_data()
        self.context = self.gate.validate_context(self.env, self.event)

    def package(self):
        return self.gate.verify_artifact(self.fixture.artifacts, SHA, self.fixture.catalog)

    def test_valid_package_and_exact_trigger_pass(self):
        package = self.package()
        self.assertEqual(set(package['assets']), {self.fixture.name, self.fixture.name + '.sha256', 'build-metadata.json'})
        self.assertEqual(self.context['sha'], SHA)

    def test_every_gate_mismatch_fails_closed(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                           ('GITHUB_REF', 'refs/heads/other'), ('GITHUB_REPOSITORY', 'other/repo'),
                           ('GITHUB_SHA', 'b' * 40), ('BUILD_RESULT', 'failure'),
                           ('PORTABLE_RESULT', 'skipped'), ('GITHUB_RUN_ID', 'x'), ('GITHUB_RUN_ATTEMPT', '0')]:
            with self.subTest(key=key), self.assertRaises(self.gate.GateError):
                self.gate.validate_context({**self.env, key: value}, self.event)
        for message in [TRIGGER + '\n', TRIGGER + '\n\nbody', 'anything', TRIGGER.upper()]:
            event = deepcopy(self.event); event['head_commit']['message'] = message
            with self.subTest(message=message), self.assertRaises(self.gate.GateError):
                self.gate.validate_context(self.env, event)
        for key, value in [('deleted', True), ('after', 'b' * 40), ('ref', 'refs/heads/other')]:
            with self.subTest(key=key), self.assertRaises(self.gate.GateError):
                self.gate.validate_context(self.env, {**self.event, key: value})

    def test_sidecar_package_hash_and_extra_artifact_are_rejected(self):
        (self.fixture.artifacts / (self.fixture.name + '.sha256')).write_text('0' * 64 + ' *' + self.fixture.name + '\n')
        with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.write(outer_changes={'sha256': '0' * 64})
        with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.write()
        (self.fixture.artifacts / 'extra').write_text('unexpected')
        with self.assertRaises(self.gate.GateError): self.package()

    def test_stale_inner_or_outer_build_identity_is_rejected(self):
        for key, bad in [('cn_commit', 'b' * 40), ('upstream_commit', 'b' * 40), ('variant', 'full'),
                         ('configuration', 'Debug'), ('platform', 'x86'), ('toolset', 'v142')]:
            with self.subTest(key=key):
                self.fixture.write(outer_changes={key: bad})
                with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.inner['cn_commit'] = 'b' * 40
        self.fixture.write()
        with self.assertRaises(self.gate.GateError): self.package()

    def test_inner_manifest_binary_digest_and_pe_format_are_checked(self):
        self.fixture.write(manifest_changes={'README.md': '0' * 64})
        with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.inner['binaries'][0]['sha256'] = '0' * 64
        self.fixture.write()
        with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.payload['OptiScaler.dll'] = b'not a DLL'
        self.fixture.inner['binaries'][0]['sha256'] = digest(b'not a DLL')
        self.fixture.write()
        with self.assertRaises(self.gate.GateError): self.package()

    def test_chinese_installer_fingerprint_and_original_manifest_are_required(self):
        for name in ['setup_windows.bat', 'setup_linux.sh', 'get_streamline.ps1', 'redist/streamline/manifest.json']:
            with self.subTest(name=name):
                old = self.fixture.payload[name]
                self.fixture.payload[name] = b'changed or English-only'
                self.fixture.write()
                with self.assertRaises(self.gate.GateError): self.package()
                self.fixture.payload[name] = old

    def test_traversal_case_collisions_and_proprietary_payload_are_rejected(self):
        for name in ['../evil', '/evil', 'C:/evil', 'dir\\evil', 'CON.txt', 'trailing./x', 'optiscaler.dll',
                     'nvngx_dlssnr.dll', 'sl.interposer.dll', 'OptiScaler/debug.pdb']:
            with self.subTest(name=name):
                self.fixture.payload[name] = b'x'; self.fixture.write()
                with self.assertRaises(self.gate.GateError): self.package()
                del self.fixture.payload[name]

    def test_missing_extra_or_tampered_hybrid_resource_is_rejected(self):
        self.fixture.inner['hybrid_assets'].pop()
        self.fixture.write()
        with self.assertRaises(self.gate.GateError): self.package()

    def test_draft_upload_verified_download_then_publish(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        url = self.gate.publish(package, self.context, github)
        self.assertEqual(url, f'https://github.com/{REPO}/releases/tag/{TAG}')
        self.assertEqual(github.tag, SHA)
        self.assertIs(github.release['draft'], False)
        self.assertIs(github.release['prerelease'], True)
        self.assertEqual(github.release['make_latest'], 'false')
        self.assertEqual(github.mutations[0][0], 'POST')
        self.assertTrue(github.mutations[0][2]['draft'])
        self.assertEqual(github.mutations[-1][0], 'PATCH')
        self.assertEqual(len(github.assets), 3)

    def test_created_draft_is_read_back_by_id_despite_delayed_list_visibility(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        original_api = github.api
        reads = []
        def api(method, path, payload=None):
            reads.append((method, path))
            if method == 'GET' and '/releases?' in path:
                return []
            return original_api(method, path, payload)
        github.api = api
        self.gate.publish(package, self.context, github)
        self.assertIs(github.release['draft'], False)
        self.assertTrue(any(path.endswith('/releases/7') for method, path in reads if method == 'GET'))
        self.assertEqual(sum(method == 'POST' for method, _ in reads), 1)

    def test_created_draft_id_read_retries_only_reads(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        original_api = github.api
        missing_reads = []
        def api(method, path, payload=None):
            if method == 'GET' and path.endswith('/releases/7') and len(missing_reads) < 2:
                missing_reads.append(path)
                raise self.gate.GitHubError('draft is not visible yet')
            return original_api(method, path, payload)
        github.api = api
        self.gate.publish(package, self.context, github)
        self.assertEqual(len(missing_reads), 2)
        self.assertIs(github.release['draft'], False)
        self.assertEqual(sum(item[0] == 'POST' for item in github.mutations), 1)

    def test_malformed_successful_create_reply_never_triggers_another_mutation(self):
        for bad_id in (None, True, 0, '7'):
            package = self.package(); github = FakeGitHub(self.gate, package, self.context)
            original_api = github.api
            def api(method, path, payload=None):
                value = original_api(method, path, payload)
                if method == 'POST': value['id'] = bad_id
                return value
            github.api = api
            with self.subTest(bad_id=bad_id), self.assertRaises(self.gate.GateError):
                self.gate.publish(package, self.context, github)
            self.assertEqual([item[0] for item in github.mutations], ['POST'])

    def test_exact_existing_release_is_no_op(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        self.gate.publish(package, self.context, github)
        github.mutations.clear()
        self.gate.publish(package, self.context, github)
        self.assertEqual(github.mutations, [])

    def test_release_conflicts_never_mutate_remote_state(self):
        for defect in ['tag', 'commit', 'prerelease', 'asset', 'extra-asset', 'body']:
            with self.subTest(defect=defect):
                package = self.package(); github = FakeGitHub(self.gate, package, self.context)
                self.gate.publish(package, self.context, github)
                if defect == 'tag': github.tag = 'b' * 40
                if defect == 'commit': github.release['target_commitish'] = 'b' * 40
                if defect == 'prerelease': github.release['prerelease'] = False
                if defect == 'asset': github.assets['build-metadata.json'] = b'bad'
                if defect == 'extra-asset': github.assets['extra'] = b'bad'
                if defect == 'body': github.release['body'] = 'unowned release'
                github.mutations.clear()
                with self.assertRaises(self.gate.GateError): self.gate.publish(package, self.context, github)
                self.assertEqual(github.mutations, [])

    def test_orphan_tag_failed_job_or_advanced_main_prevents_creation(self):
        for defect in ['tag', 'build', 'main']:
            package = self.package(); github = FakeGitHub(self.gate, package, self.context)
            if defect == 'tag': github.tag = SHA
            if defect == 'build': github.build_result = 'failure'
            if defect == 'main': github.main_sha = 'b' * 40
            with self.subTest(defect=defect), self.assertRaises(self.gate.GateError):
                self.gate.publish(package, self.context, github)
            self.assertEqual(github.mutations, [])

    def test_lost_mutation_replies_are_reconciled_before_continuing(self):
        for operation in ['create', 'upload', 'publish']:
            with self.subTest(operation=operation):
                package = self.package(); github = FakeGitHub(self.gate, package, self.context)
                github.fail_after = operation
                self.gate.publish(package, self.context, github)
                self.assertIs(github.release['draft'], False)
                self.assertEqual(len([x for x in github.mutations if x[0] == 'POST']), 1)
                self.assertEqual(len([x for x in github.mutations if x[0] == 'PATCH']), 1)
                self.assertEqual(len([x for x in github.mutations if x[0] == 'UPLOAD']), 3)

    def test_draft_with_partial_verified_assets_is_resumed_without_overwrite(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        github.release = {**self.gate.release_payload(package, self.context), 'id': 7}
        first = next(iter(package['assets']))
        github.assets[first] = package['assets'][first].read_bytes()
        self.gate.publish(package, self.context, github)
        self.assertIs(github.release['draft'], False)
        self.assertEqual(len([x for x in github.mutations if x[0] == 'UPLOAD']), 2)

    def test_remote_byte_mismatch_leaves_draft_unpublished(self):
        package = self.package(); github = FakeGitHub(self.gate, package, self.context)
        github.bad_download = True
        with self.assertRaises(self.gate.GateError): self.gate.publish(package, self.context, github)
        self.assertIs(github.release['draft'], True)
        self.assertFalse(any(x[0] == 'PATCH' for x in github.mutations))

    def test_empty_token_is_rejected_without_calling_gh(self):
        for env in ({k: v for k, v in self.env.items() if k != 'GH_TOKEN'}, {**self.env, 'GH_TOKEN': ''}):
            with self.assertRaises(self.gate.GateError):
                self.gate.validate_context(env, self.event)

    def test_manifest_cannot_omit_or_add_files(self):
        self.fixture.write(manifest_changes={'not-present': '0' * 64})
        with self.assertRaises(self.gate.GateError): self.package()
        self.fixture.write()
        self.fixture.payload['SHA256SUMS.txt'] = b''
        # Update outer hashes, but leave the deliberately empty inner manifest.
        path = self.fixture.artifacts / self.fixture.name
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in self.fixture.payload.items(): archive.writestr(name, data)
        metadata = json.loads((self.fixture.artifacts / 'build-metadata.json').read_text(encoding='utf-8-sig'))
        metadata['sha256'] = digest(path.read_bytes())
        (self.fixture.artifacts / 'build-metadata.json').write_text(json.dumps(metadata))
        (self.fixture.artifacts / (self.fixture.name + '.sha256')).write_text(metadata['sha256'] + ' *' + self.fixture.name + '\n')
        with self.assertRaises(self.gate.GateError): self.package()

    def test_duplicate_json_keys_are_rejected(self):
        path = self.fixture.artifacts / 'build-metadata.json'
        original = path.read_text(encoding='utf-8-sig')
        path.write_text('{"cn_commit":"wrong",' + original[1:])
        with self.assertRaises(self.gate.GateError): self.package()

    def test_zip_symlink_is_rejected(self):
        path = self.fixture.artifacts / self.fixture.name
        with zipfile.ZipFile(path, 'a') as archive:
            entry = zipfile.ZipInfo('linked')
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, b'OptiScaler.dll')
        metadata_path = self.fixture.artifacts / 'build-metadata.json'
        metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig'))
        metadata['sha256'] = digest(path.read_bytes())
        metadata_path.write_text(json.dumps(metadata))
        (self.fixture.artifacts / (self.fixture.name + '.sha256')).write_text(metadata['sha256'] + ' *' + self.fixture.name + '\n')
        with self.assertRaises(self.gate.GateError): self.package()

    def test_unresolved_mutations_stop_without_blind_retry(self):
        for operation in ['create', 'upload', 'publish']:
            with self.subTest(operation=operation):
                package = self.package(); github = FakeGitHub(self.gate, package, self.context)
                original_api = github.api
                attempts = []
                def api(method, path, payload=None):
                    if (operation == 'create' and method == 'POST') or (operation == 'publish' and method == 'PATCH'):
                        attempts.append(method)
                        raise self.gate.GitHubError('request did not arrive')
                    return original_api(method, path, payload)
                def upload(path):
                    attempts.append('UPLOAD')
                    raise self.gate.GitHubError('request did not arrive')
                github.api = api
                if operation == 'upload': github.upload = upload
                with self.assertRaises(self.gate.GateError): self.gate.publish(package, self.context, github)
                self.assertEqual(len(attempts), 1)
                self.assertTrue(github.release is None or github.release['draft'])

    def test_incomplete_or_extra_draft_assets_cannot_be_replaced(self):
        for state in ['starter', 'extra']:
            package = self.package(); github = FakeGitHub(self.gate, package, self.context)
            github.release = {**self.gate.release_payload(package, self.context), 'id': 7}
            name = next(iter(package['assets']))
            github.assets[name if state == 'starter' else 'unexpected'] = b''
            with self.subTest(state=state), self.assertRaises(self.gate.GateError):
                self.gate.publish(package, self.context, github)
            self.assertEqual(github.mutations, [])

    def test_run_provenance_and_job_conclusions_are_independently_checked(self):
        for change in ['run-sha', 'run-path', 'attempt', 'duplicate-job', 'missing-job']:
            package = self.package(); github = FakeGitHub(self.gate, package, self.context)
            original_api = github.api
            def api(method, path, payload=None):
                data = original_api(method, path, payload)
                if path.endswith('actions/runs/123'):
                    if change == 'run-sha': data['head_sha'] = 'b' * 40
                    if change == 'run-path': data['path'] = '.github/workflows/other.yml'
                    if change == 'attempt': data['run_attempt'] = 2
                if 'jobs?' in path:
                    if change == 'duplicate-job': data['jobs'].append(deepcopy(data['jobs'][0]))
                    if change == 'missing-job': data['jobs'].pop()
                return data
            github.api = api
            with self.subTest(change=change), self.assertRaises(self.gate.GateError):
                self.gate.publish(package, self.context, github)
            self.assertEqual(github.mutations, [])

    def test_transport_uses_fixed_host_repository_and_no_overwrite(self):
        self.block.stop()
        with patch.object(self.gate.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'{}'
            run.return_value.stderr = b''
            github = self.gate.GitHub()
            github.api('POST', 'repos/' + REPO + '/releases', self.gate.release_payload(self.package(), self.context))
            command = run.call_args.args[0]
            self.assertIn('--hostname', command); self.assertIn('github.com', command)
            self.assertIn('--input', command)
            github.upload(self.fixture.artifacts / self.fixture.name)
            command = run.call_args.args[0]
            self.assertIn('github.com/' + REPO, command)
            self.assertNotIn('--clobber', command)
            with self.assertRaises(self.gate.GateError):
                github.api('DELETE', 'repos/' + REPO + '/releases/7')


if __name__ == '__main__':
    unittest.main()
