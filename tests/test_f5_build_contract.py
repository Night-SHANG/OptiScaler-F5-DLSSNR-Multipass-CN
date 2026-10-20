"""Portable safety/contract tests; these do not claim a Windows build ran."""
from pathlib import Path
import importlib.util
import json
import subprocess
import shutil
import zipfile
import tempfile
import unittest
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.spec_from_file_location('prepare_tree', ROOT / 'tools/prepare_tree.py')
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
REPOSITORY = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'


class PrepareTreeSafetyTests(unittest.TestCase):
    def test_config_requires_a_full_current_commit_and_fixed_repository(self):
        valid = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
        self.assertTrue(hasattr(prepare, 'validate_config'), 'exact-pin validation is required')
        prepare.validate_config(valid)
        prepare.validate_config({**valid, 'commit': 'a' * 40, 'upstream_version': 'v0.1.33'})
        prepare.validate_config({**valid, 'commit': 'a' * 40, 'upstream_version': 'main-' + 'a' * 12})
        for key, value in [('commit', 'main'), ('commit', 'auto'), ('commit', 'a'*39),
                           ('commit', 'A'*40), ('commit', 'a'*40 + '\n'), ('commit', '--upload-pack=evil'),
                           ('repository', 'https://example.com/repo'), ('branch', 'other'),
                           ('upstream_version', 'v0.1.33\n'),
                           ('upstream_version', 'v0.1.33; Write-Host injected'),
                           ('upstream_version', 'main-' + 'b' * 12)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prepare.validate_config({**valid, key: value})

    def test_checkout_uses_current_pin_and_runs_pristine_contract(self):
        cfg = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
        cfg.update(commit='a' * 40, upstream_version='v0.1.33')
        contract = prepare.load_contract(ROOT / 'upstream-contract.json')
        status = ' ' + 'b' * 40 + ' external/test\n'
        with mock.patch.object(prepare, 'verify_source') as gate, \
             mock.patch.object(prepare, 'run', return_value=''), \
             mock.patch.object(prepare.subprocess, 'check_output', return_value=status):
            self.assertEqual(prepare.verify_checkout(ROOT / '_upstream', cfg, contract), status)
        gate.assert_called_once_with(ROOT / '_upstream', cfg, contract)

    def test_materialization_gates_current_pin_before_recursive_submodules(self):
        cfg = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
        cfg.update(commit='a' * 40, upstream_version='v0.1.33')
        contract = prepare.load_contract(ROOT / 'upstream-contract.json')
        for reject in (False, True):
            with self.subTest(reject=reject), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                (root / 'upstream.json').write_text(json.dumps(cfg), encoding='utf-8')
                events = []
                def run(*args, cwd=None):
                    events.append(args)
                    if args[:2] == ('git', 'clone'):
                        Path(args[-1]).mkdir()
                    return ''
                def gate(path, actual_cfg, actual_contract):
                    events.append(('contract', actual_cfg['commit']))
                    self.assertEqual(actual_cfg, cfg)
                    self.assertEqual(actual_contract, contract)
                    owner = json.loads((path / prepare.MARKER).read_text(encoding='utf-8'))
                    self.assertEqual(owner['commit'], cfg['commit'])
                    if reject:
                        raise ValueError('Untrusted candidate fixture')
                with mock.patch.object(prepare, 'ROOT', root), \
                     mock.patch.object(prepare, 'load_contract', return_value=contract), \
                     mock.patch.object(prepare, 'run', side_effect=run), \
                     mock.patch.object(prepare, 'verify_source', side_effect=gate), \
                     mock.patch.object(prepare.subprocess, 'check_output', return_value=' ' + 'b' * 40 + ' external/test\n'), \
                     mock.patch.object(sys, 'argv', ['prepare_tree.py']):
                    if reject:
                        with self.assertRaisesRegex(ValueError, 'Untrusted candidate'):
                            prepare.main()
                    else:
                        self.assertEqual(prepare.main(), 0)
                self.assertIn(('git', 'fetch', '--no-tags', '--depth=1', 'origin', cfg['commit']), events)
                self.assertIn(('git', 'checkout', '--detach', cfg['commit']), events)
                recursive = [index for index, event in enumerate(events) if 'submodule' in event]
                if reject:
                    self.assertEqual(recursive, [])
                    self.assertFalse((root / 'reports/upstream-materialization.json').exists())
                else:
                    self.assertEqual(len(recursive), 1)
                    self.assertLess(events.index(('contract', cfg['commit'])), recursive[0])
                    self.assertGreater(len(events) - 1 - events[::-1].index(('contract', cfg['commit'])), recursive[0])
                    report = json.loads((root / 'reports/upstream-materialization.json').read_text(encoding='utf-8'))
                    self.assertEqual(report['upstream_commit'], cfg['commit'])
                    self.assertEqual(report['upstream_version'], cfg['upstream_version'])

    def test_owned_previous_exact_pin_can_be_replaced_but_mismatch_cannot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            tree = root / '_upstream'
            tree.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=tree, stderr=subprocess.STDOUT).decode().strip()
            git('init')
            git('remote', 'add', 'origin', REPOSITORY)
            (tree / 'owned.txt').write_text('owned fixture', encoding='utf-8')
            git('add', 'owned.txt')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
            old_pin = git('rev-parse', 'HEAD')
            owner = {'schema': 1, 'root': str(root), 'repository': REPOSITORY, 'commit': old_pin}
            marker = tree / prepare.MARKER
            for invalid in ('main', 'a' * 40):
                marker.write_text(json.dumps({**owner, 'commit': invalid}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    prepare.clean_owned_worktree(root, tree)
                self.assertTrue((tree / 'owned.txt').exists())
            marker.write_text(json.dumps(owner), encoding='utf-8')
            prepare.clean_owned_worktree(root, tree)
            self.assertFalse(tree.exists())

    def test_only_exact_owned_child_can_be_deleted(self):
        self.assertTrue(hasattr(prepare, 'bounded_worktree'), 'bounded path validation is required')
        with tempfile.TemporaryDirectory() as td:
            # Windows temporary directories can contain an 8.3 alias; test the canonical owned root.
            root = Path(td).resolve()
            self.assertEqual(prepare.bounded_worktree(root, root / '_upstream'), root / '_upstream')
            for unsafe in [root, root.parent, root / 'other', root / '_upstream/child']:
                with self.subTest(unsafe=str(unsafe)), self.assertRaises(ValueError):
                    prepare.bounded_worktree(root, unsafe)
            external = root / 'external'; external.mkdir()
            (root / '_upstream').symlink_to(external, target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare.bounded_worktree(root, root / '_upstream')

    def test_unowned_tree_is_never_removed(self):
        self.assertTrue(hasattr(prepare, 'clean_owned_worktree'), 'ownership verification is required')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); tree = root / '_upstream'; tree.mkdir()
            precious = tree / 'keep.txt'; precious.write_text('keep')
            with self.assertRaises(ValueError):
                prepare.clean_owned_worktree(root, tree)
            self.assertEqual(precious.read_text(), 'keep')

    def test_checkout_pins_lf_even_with_a_crlf_default(self):
        source = (ROOT / 'tools/prepare_tree.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('"core.eol=lf"'), 2)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            origin = root / 'origin'; origin.mkdir()
            def git(*args, cwd=origin):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.STDOUT)
            git('init')
            (origin / '.gitattributes').write_bytes(b'* text=auto\n')
            (origin / 'test.cpp').write_bytes(b'#include "pch.h"\nint x;\n')
            git('-c', 'core.autocrlf=false', 'add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
            # Simulate Windows/native or an inherited CRLF checkout policy.
            git('-c', 'core.eol=crlf', 'clone', '--no-checkout', '-c', 'core.autocrlf=false',
                '-c', 'core.eol=lf', str(origin), str(root / 'tree'))
            git('checkout', '--detach', 'HEAD', cwd=root / 'tree')
            self.assertEqual((root / 'tree/test.cpp').read_bytes(), b'#include "pch.h"\nint x;\n')

    def test_submodules_must_be_initialized_at_exact_gitlinks(self):
        self.assertTrue(hasattr(prepare, 'validate_submodule_status'), 'recursive pin checking is required')
        prepare.validate_submodule_status(' ' + 'a'*40 + ' external/test (heads/main)\n')
        for prefix in ['-', '+', 'U']:
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                prepare.validate_submodule_status(prefix + 'a'*40 + ' external/test\n')
        with self.assertRaises(ValueError):
            prepare.validate_submodule_status('')


class BuildContractTests(unittest.TestCase):
    def text(self, relative):
        path = ROOT / relative
        self.assertTrue(path.is_file(), relative)
        return path.read_text(encoding='utf-8')

    def test_workflow_keeps_build_read_only_and_gates_test_publication(self):
        text = self.text('.github/workflows/build.yml')
        for token in ['workflow_dispatch:', 'push:', 'branches: [main]', 'contents: read', 'windows-2022']:
            self.assertIn(token, text)
        for token in ['portable-contracts:', 'runs-on: ubuntu-24.04', 'g++ --version',
                      'python tests/test_f5_display_runtime.py --repo .', 'set -euo pipefail']:
            self.assertIn(token, text)
        build, release = text.split('  publish-test-release:', 1)
        release = release.split('  publish-synced-test-release:', 1)[0]
        self.assertNotIn('contents: write', build)
        self.assertEqual(release.count('contents: write'), 1)
        for token in ["needs: [portable-contracts, build]", "github.event_name == 'push'",
                      "github.ref == 'refs/heads/main'", "release: publish v0.1.32-cn-test.1",
                      "needs.portable-contracts.result == 'success'", "needs.build.result == 'success'",
                      'actions/download-artifact@v4', 'needs.build.outputs.artifact_name',
                      'python tools/publish_test_release.py --artifact-dir release-artifact']:
            self.assertIn(token, release)
        for forbidden in ['schedule:', 'actions: write', 'action-gh-release', 'gh release']:
            self.assertNotIn(forbidden, text)

    def test_synced_publication_is_explicit_exact_sha_dispatch_with_both_build_gates(self):
        text = self.text('.github/workflows/build.yml')
        release = text.split('  publish-synced-test-release:', 1)[1]
        for token in ["needs: [portable-contracts, build]", "github.event_name == 'workflow_dispatch'",
                      "inputs.sync_publish == true", "inputs.expected_sha == github.sha",
                      "github.ref == 'refs/heads/main'", "github.repository == 'Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN'",
                      "needs.portable-contracts.result == 'success'", "needs.build.result == 'success'",
                      'contents: write', 'actions: read', 'needs.build.outputs.artifact_name',
                      'python tools/publish_synced_release.py']:
            self.assertIn(token, release)
        self.assertIn('expected_sha:', text)
        self.assertIn('sync_publish:', text)
        self.assertNotIn('schedule:', text)

    def test_artifact_identity_is_attempt_qualified_and_bound_to_successful_build_output(self):
        text = self.text('.github/workflows/build.yml')
        build = text.split('  publish-test-release:', 1)[0]
        self.assertIn('artifact_name: ${{ steps.package-identity.outputs.name }}', build)
        self.assertIn('OptiScaler-F5-CN-${{ github.sha }}-${{ github.run_attempt }}', build)
        self.assertIn('name: ${{ steps.package-identity.outputs.name }}', build)
        self.assertEqual(text.count('name: ${{ needs.build.outputs.artifact_name }}'), 2)
        self.assertNotIn('overwrite:', text)

    def test_strict_preflight_precedes_actual_msvc_build(self):
        text = self.text('.github/workflows/build.yml')
        strict = text.index('check_localization.py --strict --channel master')
        localize = text.index('localize_f5.py --source _upstream')
        build = text.index('msbuild _upstream\\OptiScaler.sln')
        self.assertLess(strict, localize); self.assertLess(localize, build)
        for token in ['git diff --exit-code -- Localization', '/p:Configuration=Release', '/p:Platform=x64', '/p:PlatformToolset=v143',
                      'dlssnr_forwarder.vcxproj', 'if: always()', 'build-diagnostics', '$LASTEXITCODE']:
            self.assertIn(token, text)
        for forbidden in ['localize_source.py', 'PostBuildEventUseInBuild=false', '/p:PostBuildEvent=']:
            self.assertNotIn(forbidden, text)

    def test_packager_uses_fixed_downloader_only_upstream_contract(self):
        text = self.text('tools/package.ps1')
        for token in ['package_release.ps1', 'get_hybrid_assets.ps1', 'HybridAssetsDirectory',
                      "'-SkipBuild'", 'nvngx.dll_dlssnr.dll', 'nvngx_dlssnr.dll',
                      'asset-manifest.json', 'build-metadata.json', 'SHA256SUMS.txt',
                      'Assert-SafeArchive', 'Assert-StagedDependencies', 'HybridSource',
                      '3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037']:
            self.assertIn(token, text)
        for forbidden in ['IncludeDlssFrameGeneration', 'AcceptNvidiaLicenses', 'IncludeAmpereMfg',
                          'AcceptAmpereMfgLicenses', 'EnableRtx40Mfg', 'patchedPackagerText']:
            self.assertNotIn(forbidden, text)

    def test_packager_reads_current_identity_before_upstream_execution(self):
        text = self.text('tools/package.ps1')
        for token in ['$pin = [string]$cfg.commit', '$version = [string]$cfg.upstream_version',
                      'Assert-UpstreamConfig $cfg', 'validate_config', 'load_contract',
                      'upstream-contract.json']:
            self.assertIn(token, text)
        self.assertNotIn("$pin = '" + PIN + "'", text)
        self.assertNotIn("$version = 'v0.1.32'", text)
        self.assertLess(text.index('Assert-UpstreamConfig $cfg'),
                        text.index('Invoke-PinnedPowerShellScript $hybridFetcher'))
        for fingerprint in ('ceb7cf129a654591e70f897c0ba410039a94eb626c507fd252584969ff4a5a1c',
                            '5fcd0c8018c1030e63e664d5df56e9a757bdafda77df688354cd4527e90172b1',
                            '516fb296ea12deab12a2d35a1a96ea1a87955a3bfeb3e2bb1a033b0519c7d774'):
            self.assertIn(fingerprint, text)

    def test_build_import_exception_is_not_used_for_public_stage(self):
        text = self.text('tools/package.ps1')
        self.assertIn('Assert-NoForbiddenPayload $builtStage -AllowForwarderBuildImports', text)
        self.assertIn('Assert-NoForbiddenPayload $stage\n', text)
        self.assertNotIn('Assert-NoForbiddenPayload $stage -AllowForwarderBuildImports', text)
        self.assertEqual(text.count('-AllowForwarderBuildImports'), 1)
        self.assertIn("'nvngx.dll_dlssnr.lib'", text)
        self.assertIn("'nvngx.dll_dlssnr.exp'", text)

    def test_upstream_scripts_run_in_isolated_powershell_with_exit_checks(self):
        text = self.text('tools/package.ps1')
        for token in ['Set-StrictMode -Version Latest', 'Invoke-PinnedPowerShellScript $upstreamPackager',
                      'Invoke-PinnedPowerShellScript $hybridFetcher', '-NoProfile -NonInteractive -File',
                      'if ($LASTEXITCODE -ne 0)', 'Assert-Hash $upstreamPackager', 'Assert-Hash $hybridFetcher']:
            self.assertIn(token, text)
        self.assertNotIn('Set-StrictMode -Off', text)
        self.assertNotIn('& $upstreamPackager @', text)

    def test_package_records_cn_upstream_and_binary_hashes(self):
        text = self.text('tools/package.ps1')
        for token in ['cn_commit', 'upstream_commit', 'upstream_version', 'SHA256',
                      'build-evidence.json', 'Assert-Pe64', 'assert', 'submodule']:
            self.assertIn(token.lower(), text.lower())

    def test_prepare_has_no_ref_or_submodule_bypass(self):
        text = self.text('tools/prepare_tree.py')
        self.assertIn('upstream-contract.json', text)
        self.assertIn('verify_source(path, cfg, contract)', text)
        self.assertNotIn('verify_worktree=False', text)
        self.assertLess(text.index('verify_source(path, cfg, contract)', text.index('run("git", "checkout"')),
                        text.index('"submodule", "update"'))
        self.assertIn('"--recursive"', text)
        self.assertNotIn('--no-submodules', text)
        self.assertNotIn("default='master'", text)


class PowerShellValidationTests(unittest.TestCase):
    """Run AST and malicious-input probes wherever PowerShell is installed (CI Windows)."""
    def setUp(self):
        self.pwsh = shutil.which('pwsh')
        if not self.pwsh:
            self.skipTest('PowerShell unavailable; Windows script execution is not verified here')

    def invoke(self, script):
        prefix = "$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest; "
        result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-Command', prefix + script],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def load_functions(self):
        path = str(ROOT / 'tools/package.ps1').replace("'", "''")
        return ("$tokens=$null; $errors=$null; "
                f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors); "
                "if ($errors.Count) { throw ($errors | Out-String) }; "
                "foreach ($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $true)) { "
                "Invoke-Expression $function.Extent.Text }; "
                "Add-Type -AssemblyName System.IO.Compression.FileSystem; ")

    def test_package_script_parses_and_functions_load(self):
        self.invoke(self.load_functions())

    def test_package_config_accepts_exact_new_pin_and_rejects_injection(self):
        valid = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
        valid.update(commit='a' * 40, upstream_version='v0.1.33')
        values = [(None, None), ('commit', 'main'), ('commit', 'A' * 40),
                  ('commit', 'a' * 39), ('commit', 'a' * 40 + '\n'),
                  ('branch', 'release'), ('repository', 'https://example.com/repo'),
                  ('upstream_version', 'v0.1.33; Write-Host injected'),
                  ('upstream_version', 'v0.1.33\n'),
                  ('upstream_version', 'main-' + 'b' * 12), ('package_prefix', '../escape')]
        for key, value in values:
            with self.subTest(key=key, value=value):
                cfg = valid if key is None else {**valid, key: value}
                serialized = json.dumps(cfg).replace("'", "''")
                script = self.load_functions() + f"$cfg='{serialized}' | ConvertFrom-Json; "
                if key is None:
                    script += 'Assert-UpstreamConfig $cfg'
                else:
                    script += ("$rejected=$false; try { Assert-UpstreamConfig $cfg } catch { $rejected=$true }; "
                               "if (-not $rejected) { throw 'Unsafe upstream config accepted' }")
                self.invoke(script)

    def test_archive_validator_rejects_traversal_duplicate_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = {
                'safe': [('OptiScaler/file.dll', b'example')],
                'parent': [('../escape', b'x')],
                'absolute': [('/escape', b'x')],
                'drive': [('C:/escape', b'x')],
                'backslash': [('dir\\escape', b'x')],
                'case_collision': [('file', b'x'), ('FILE', b'y')],
                'reserved': [('CON.txt', b'x')],
                'trailing_dot': [('folder./file', b'x')],
            }
            for name, contents in cases.items():
                with zipfile.ZipFile(root / (name + '.zip'), 'w') as archive:
                    for filename, data in contents:
                        # ZipInfo(filename) normalizes backslashes on Windows.
                        # Set the raw member name after construction so this is
                        # genuinely the hostile archive the validator must reject.
                        info = zipfile.ZipInfo('fixture')
                        info.filename = filename
                        info.orig_filename = filename
                        archive.writestr(info, data)
                raw_zip = (root / (name + '.zip')).read_bytes()
                for filename, _ in contents:
                    # Inspect raw bytes: Python also normalizes names when
                    # reopening ZIPs on Windows, unlike the .NET validator.
                    self.assertIn(filename.encode('utf-8'), raw_zip)
            script = self.load_functions()
            for name in cases:
                path = str(root / (name + '.zip')).replace("'", "''")
                if name == 'safe':
                    script += f"Assert-SafeArchive '{path}'; "
                else:
                    script += (f"$rejected=$false; try {{ Assert-SafeArchive '{path}' }} catch {{ $rejected=$true }}; "
                               f"if (-not $rejected) {{ throw 'Accepted unsafe archive: {name}' }}; ")
            self.invoke(script)

    def test_import_libraries_allowed_only_in_build_root_never_public_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for name in ('nvngx.dll_dlssnr.lib', 'nvngx.dll_dlssnr.exp'):
                (root / name).write_bytes(b'compiler intermediate')
            path = str(root).replace("'", "''")
            prefix = self.load_functions()
            self.invoke(prefix + f"Assert-NoForbiddenPayload '{path}' -AllowForwarderBuildImports")
            reject = (f"$rejected=$false; try {{ Assert-NoForbiddenPayload '{path}' {{flag}} }} "
                      "catch { $rejected=$true }; if (-not $rejected) { throw 'Unsafe payload accepted' }")
            self.invoke(prefix + reject.replace('{flag}', ''))
            for name in ('other.lib', 'OptiScaler.pdb', 'nvngx_dlssnr.dll', 'sl.common.dll',
                         'child/nvngx.dll_dlssnr.lib'):
                file = root / name; file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'must never be accepted')
                self.invoke(prefix + reject.replace('{flag}', '-AllowForwarderBuildImports'))
                file.unlink()

    def test_child_powershell_does_not_inherit_strictmode_and_nonzero_exit_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            child = root / 'child script.ps1'
            # The upstream directory summary intentionally relies on default
            # missing-property behavior; it must not inherit our strict mode.
            # PSCustomObject itself synthesizes Length/Count, so use a truly
            # absent fixture property to distinguish strict and default modes.
            child.write_bytes(b"param([string]$Expected)\nif ($Expected -ne 'space value') { exit 9 }\n"
                              b"$null = ([pscustomobject]@{Name='directory'}).MissingPropertyFixture\nexit 0\n")
            path = str(child).replace("'", "''")
            prefix = self.load_functions()
            self.invoke(prefix + f"Invoke-PinnedPowerShellScript '{path}' @('-Expected', 'space value'); "
                        "$strict=$false; try { $null=([pscustomobject]@{Name='directory'}).MissingPropertyFixture } catch { $strict=$true }; "
                        "if (-not $strict) { throw 'Parent verifier lost StrictMode' }")
            child.write_bytes(b'exit 7\n')
            self.invoke(prefix + f"$rejected=$false; try {{ Invoke-PinnedPowerShellScript '{path}' @() }} "
                        "catch { $rejected=$true }; if (-not $rejected) { throw 'Nonzero child exit accepted' }")

    def test_pe_validator_requires_real_x64_dll_headers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'fixture.dll'
            data = bytearray(256)
            data[:2] = b'MZ'
            data[0x3c:0x40] = (0x80).to_bytes(4, 'little')
            data[0x80:0x84] = b'PE\0\0'
            data[0x84:0x86] = (0x8664).to_bytes(2, 'little')
            data[0x96:0x98] = (0x2000).to_bytes(2, 'little')
            data[0x98:0x9a] = (0x20b).to_bytes(2, 'little')
            path.write_bytes(data)
            quoted = str(path).replace("'", "''")
            self.invoke(self.load_functions() + f"Assert-Pe64 '{quoted}'")
            data[0x84:0x86] = (0x14c).to_bytes(2, 'little')
            path.write_bytes(data)
            self.invoke(self.load_functions() +
                        f"$rejected=$false; try {{ Assert-Pe64 '{quoted}' }} catch {{ $rejected=$true }}; "
                        "if (-not $rejected) { throw 'Accepted x86 DLL' }")


if __name__ == '__main__':
    unittest.main()
