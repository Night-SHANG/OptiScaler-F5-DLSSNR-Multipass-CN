"""Portable safety/contract tests; these do not claim a Windows build ran."""
from pathlib import Path
import importlib.util
import json
import subprocess
import shutil
import zipfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('prepare_tree', ROOT / 'tools/prepare_tree.py')
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
REPOSITORY = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'


class PrepareTreeSafetyTests(unittest.TestCase):
    def test_config_requires_the_fixed_full_commit_and_repository(self):
        valid = {'repository': REPOSITORY, 'commit': PIN, 'upstream_version': 'v0.1.32'}
        self.assertTrue(hasattr(prepare, 'validate_config'), 'fixed-pin validation is required')
        prepare.validate_config(valid)
        for key, value in [('commit', 'main'), ('commit', 'auto'), ('commit', 'a'*40),
                           ('repository', 'https://example.com/repo'), ('upstream_version', 'v0.7.7')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prepare.validate_config({**valid, key: value})

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
        self.assertNotIn('contents: write', build)
        self.assertEqual(release.count('contents: write'), 1)
        for token in ["needs: [portable-contracts, build]", "github.event_name == 'push'",
                      "github.ref == 'refs/heads/main'", "release: publish v0.1.32-cn-test.1",
                      "needs.portable-contracts.result == 'success'", "needs.build.result == 'success'",
                      'actions/download-artifact@v4', 'OptiScaler-F5-CN-v0.1.32-${{ github.sha }}',
                      'python tools/publish_test_release.py --artifact-dir release-artifact']:
            self.assertIn(token, release)
        for forbidden in ['schedule:', 'actions: write', 'action-gh-release', 'gh release']:
            self.assertNotIn(forbidden, text)

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
                      'SkipBuild = $true', 'nvngx.dll_dlssnr.dll', 'nvngx_dlssnr.dll',
                      'asset-manifest.json', 'build-metadata.json', 'SHA256SUMS.txt',
                      'Assert-SafeArchive', 'Assert-StagedDependencies', 'HybridSource',
                      '3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037']:
            self.assertIn(token, text)
        for forbidden in ['IncludeDlssFrameGeneration', 'AcceptNvidiaLicenses', 'IncludeAmpereMfg',
                          'AcceptAmpereMfgLicenses', 'EnableRtx40Mfg', 'patchedPackagerText']:
            self.assertNotIn(forbidden, text)

    def test_build_import_exception_is_not_used_for_public_stage(self):
        text = self.text('tools/package.ps1')
        self.assertIn('Assert-NoForbiddenPayload $builtStage -AllowForwarderBuildImports', text)
        self.assertIn('Assert-NoForbiddenPayload $stage\n', text)
        self.assertNotIn('Assert-NoForbiddenPayload $stage -AllowForwarderBuildImports', text)
        self.assertEqual(text.count('-AllowForwarderBuildImports'), 1)
        self.assertIn("'nvngx.dll_dlssnr.lib'", text)
        self.assertIn("'nvngx.dll_dlssnr.exp'", text)

    def test_package_records_cn_upstream_and_binary_hashes(self):
        text = self.text('tools/package.ps1')
        for token in ['cn_commit', 'upstream_commit', 'upstream_version', 'SHA256',
                      'build-evidence.json', 'Assert-Pe64', 'assert', 'submodule']:
            self.assertIn(token.lower(), text.lower())

    def test_prepare_has_no_ref_or_submodule_bypass(self):
        text = self.text('tools/prepare_tree.py')
        self.assertIn('fadc3bf67f6c8548e94914baec3f2e551ba8d8a4', text)
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
