"""Pinned installer display adaptation; never performs installation or downloads."""
import importlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
PIN = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))['commit']
SCRIPTS = ('setup_windows.bat', 'setup_linux.sh', 'Streamlined_fetcher_windows.bat', 'get_streamline.ps1')


def find_bash_executable(platform=None):
    """Avoid Windows' WSL bash.exe stub; use the installed Git Bash runtime."""
    if (platform or os.name) != 'nt':
        return shutil.which('bash')
    git = shutil.which('git.exe')
    if not git:
        return None
    # Git for Windows exposes git.exe from cmd/, bin/, or mingw64/bin/.
    for directory in list(Path(git).resolve().parents)[:3]:
        for relative in ('bin/bash.exe', 'usr/bin/bash.exe'):
            candidate = directory / relative
            if candidate.is_file():
                return str(candidate)
    return None


class BashSelectionTests(unittest.TestCase):
    def finder(self):
        self.assertIn('find_bash_executable', globals(),
                      'Select Git for Windows Bash explicitly instead of the WSL PATH stub')
        return globals()['find_bash_executable']

    def test_windows_prefers_git_bash_over_path_wsl_stub(self):
        finder = self.finder()
        for git_subdir in ('cmd', 'bin', 'mingw64/bin'):
            with self.subTest(git_subdir=git_subdir), tempfile.TemporaryDirectory() as temp:
                git_root = Path(temp).resolve() / 'Git'
                git = git_root / git_subdir / 'git.exe'
                bash = git_root / 'bin' / 'bash.exe'
                git.parent.mkdir(parents=True, exist_ok=True)
                bash.parent.mkdir(parents=True, exist_ok=True)
                git.touch()
                bash.touch()
                with mock.patch.object(shutil, 'which', side_effect=lambda name:
                                       str(git) if name == 'git.exe' else r'C:\Windows\System32\bash.exe') as which:
                    self.assertEqual(finder('nt'), str(bash))
                    which.assert_called_once_with('git.exe')

    def test_windows_without_git_bash_does_not_use_wsl_stub(self):
        finder = self.finder()
        with mock.patch.object(shutil, 'which', side_effect=lambda name:
                               None if name == 'git.exe' else r'C:\Windows\System32\bash.exe'):
            self.assertIsNone(finder('nt'))

    def test_linux_keeps_native_path_bash(self):
        finder = self.finder()
        with mock.patch.object(shutil, 'which', return_value='/usr/bin/bash') as which:
            self.assertEqual(finder('posix'), '/usr/bin/bash')
            which.assert_called_once_with('bash')


class InstallerAdapterTests(unittest.TestCase):
    def module(self):
        self.assertTrue((ROOT / 'tools/f5_installer_patch.py').is_file(),
                        'The installer adapter must exist before installer localization can run')
        return importlib.import_module('f5_installer_patch')

    def checkout(self, root):
        # CI prepares _upstream; local development also has the immutable sibling checkout.
        for candidate in (ROOT / '_upstream', ROOT.parent / 'upstream'):
            if (candidate / '.git').exists():
                try:
                    contents = {name: subprocess.check_output(
                        ['git', '-C', str(candidate), 'show', f'{PIN}:{name}']) for name in SCRIPTS}
                except subprocess.CalledProcessError:
                    continue
                for name, data in contents.items():
                    (root / name).write_bytes(data)
                return contents
        self.fail('Pinned upstream checkout is required; run tools/prepare_tree.py first')

    def test_translates_every_entrypoint_and_is_idempotent(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            module.patch_installer_scripts(root)
            first = {name: (root / name).read_bytes() for name in SCRIPTS}
            for name, data in first.items():
                self.assertRegex(data.decode('utf-8-sig'), '[\u4e00-\u9fff]', name)
            module.patch_installer_scripts(root)
            self.assertEqual(first, {name: (root / name).read_bytes() for name in SCRIPTS})

    def test_current_full_pin_accepts_unchanged_audited_installer_bytes(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            cfg = json.loads(module.CONFIG.read_text(encoding='utf-8'))
            catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
            cfg.update(commit='a' * 40, upstream_version='v0.1.33')
            catalog['upstream_commit'] = cfg['commit']
            config_path, catalog_path = root / 'config.json', root / 'catalog.json'
            config_path.write_text(json.dumps(cfg), encoding='utf-8')
            catalog_path.write_text(json.dumps(catalog), encoding='utf-8')
            with mock.patch.object(module, 'CONFIG', config_path), mock.patch.object(module, 'CATALOG', catalog_path):
                module.patch_installer_scripts(root)
                for record in catalog['scripts']:
                    text = (root / record['path']).read_text(encoding='utf-8-sig')
                    self.assertEqual(module._digest(text), record['localized_sha256'])

    def test_current_identity_rejects_floating_injected_and_stale_catalog_values(self):
        module = self.module()
        for field, value in [('commit', 'main'), ('commit', '--upload-pack=evil'),
                             ('upstream_version', 'v0.1.33; evil'), ('commit', 'a' * 40)]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.checkout(root)
                cfg = json.loads(module.CONFIG.read_text(encoding='utf-8'))
                cfg[field] = value
                config_path = root / 'config.json'
                config_path.write_text(json.dumps(cfg), encoding='utf-8')
                before = {name: (root / name).read_bytes() for name in SCRIPTS}
                with mock.patch.object(module, 'CONFIG', config_path), self.assertRaises((ValueError, RuntimeError)):
                    module.patch_installer_scripts(root)
                self.assertEqual(before, {name: (root / name).read_bytes() for name in SCRIPTS})

    def test_catalog_cannot_reauthorize_changed_installer_fingerprints(self):
        module = self.module()
        for field in ('source_sha256', 'localized_sha256'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.checkout(root)
                catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
                catalog['scripts'][0][field] = 'a' * 64
                path = root / 'catalog.json'
                path.write_text(json.dumps(catalog), encoding='utf-8')
                before = {name: (root / name).read_bytes() for name in SCRIPTS}
                with mock.patch.object(module, 'CATALOG', path), self.assertRaisesRegex(RuntimeError, 'immutable'):
                    module.patch_installer_scripts(root)
                self.assertEqual(before, {name: (root / name).read_bytes() for name in SCRIPTS})

    def test_source_drift_is_rejected_before_any_write(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = self.checkout(root)
            bad = root / 'get_streamline.ps1'
            bad.write_bytes(original[bad.name].replace(b"$ErrorActionPreference = 'Stop'", b"$ErrorActionPreference = 'Continue'"))
            before = {name: (root / name).read_bytes() for name in SCRIPTS}
            with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                module.patch_installer_scripts(root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in SCRIPTS})

    def test_missing_invalid_utf8_or_modified_output_is_rejected(self):
        module = self.module()
        for defect in ('missing', 'invalid-utf8', 'modified-output'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.checkout(root)
                target = root / SCRIPTS[-1]
                if defect == 'missing':
                    target.unlink()
                elif defect == 'invalid-utf8':
                    target.write_bytes(b'\xff\xfe\x00')
                else:
                    module.patch_installer_scripts(root)
                    target.write_bytes(target.read_bytes() + b'\n# drift\n')
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                    module.patch_installer_scripts(root)
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_display_anchor_drift_is_rejected_for_each_script(self):
        module = self.module()
        catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
        for record in catalog['scripts']:
            with self.subTest(name=record['path']), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.checkout(root)
                target = root / record['path']
                text = target.read_text(encoding='utf-8-sig')
                text = text.replace(record['entries'][0]['source'], record['entries'][0]['source'] + ' changed', 1)
                target.write_text(text, encoding='utf-8')
                before = {name: (root / name).read_bytes() for name in SCRIPTS}
                with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                    module.patch_installer_scripts(root)
                self.assertEqual(before, {name: (root / name).read_bytes() for name in SCRIPTS})

    def test_redist_manifest_hashes_urls_and_licenses_are_not_modified(self):
        module = self.module()
        catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
        manifest = catalog['redist']
        self.assertEqual(manifest['path'], 'redist/streamline/manifest.json')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            for upstream in (ROOT / '_upstream', ROOT.parent / 'upstream'):
                if (upstream / '.git').exists():
                    data = subprocess.check_output(['git', '-C', str(upstream), 'show',
                                                    f'{PIN}:{manifest["path"]}'])
                    break
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest['sha256'])
            path = root / manifest['path']
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            module.patch_installer_scripts(root)
            self.assertEqual(path.read_bytes(), data)

    def test_crlf_checkout_and_emitted_encodings(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = self.checkout(root)
            for name, data in original.items():
                (root / name).write_bytes(data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            module.patch_installer_scripts(root)
            for name in SCRIPTS:
                data = (root / name).read_bytes()
                data.decode('utf-8-sig')
                if name.endswith('.bat'):
                    self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
                    self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
                    first_chinese = re.search('[\u4e00-\u9fff]', data.decode('utf-8')).start()
                    self.assertLess(data.decode('utf-8').index('chcp 65001 >nul'), first_chinese)
                elif name.endswith('.ps1'):
                    self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
                else:
                    self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
                    self.assertNotIn(b'\r', data)

    def test_every_original_command_and_control_line_is_unchanged(self):
        module = self.module()
        catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            originals = self.checkout(root)
            module.patch_installer_scripts(root)
            for record in catalog['scripts']:
                name = record['path']
                output = (root / name).read_text(encoding='utf-8-sig')
                # Remove precisely the reviewed encoding/pause additions. The
                # remaining file must reconstruct the pinned source exactly.
                output = re.sub(r'^(?:echo )?REM BEGIN OPTISCALER_CN_CODEPAGE_V1\n.*?'
                                r'^(?:echo )?REM END OPTISCALER_CN_CODEPAGE_V1\n',
                                '', output, flags=re.M | re.S)
                output = output.replace('chcp %_F5_CN_OLD_CP% >nul\n', '')
                output = output.replace('echo chcp %%_F5_CN_OLD_CP%% ^>nul\n', '')
                output = re.sub(r'^([ \t]*)echo 按任意键继续 \. \. \.\n\1pause >nul$',
                                r'\1pause', output, flags=re.M)
                output = output.replace('echo echo 按任意键继续 . . .\necho pause ^>nul\n',
                                        'echo pause\n')
                lines = output.splitlines(keepends=True)
                for entry in record['entries']:
                    self.assertEqual(lines[entry['line'] - 1], entry['translation'] + '\n')
                    self.assertEqual(module._variables(entry['source']),
                                     module._variables(entry['translation']))
                    lines[entry['line'] - 1] = entry['source'] + '\n'
                self.assertEqual(''.join(lines), originals[name].decode('utf-8-sig').replace('\r\n', '\n'), name)

    def test_catalog_has_complete_display_inventory_and_retention_reasons(self):
        module = self.module()
        catalog = json.loads(module.CATALOG.read_text(encoding='utf-8'))
        expected = {'setup_windows.bat': (154, 134, 20, 4),
                    'setup_linux.sh': (76, 58, 18, 0),
                    'Streamlined_fetcher_windows.bat': (26, 24, 2, 3),
                    'get_streamline.ps1': (12, 12, 0, 0)}
        with tempfile.TemporaryDirectory() as temp:
            originals = self.checkout(Path(temp))
            for record in catalog['scripts']:
                name = record['path']
                lines = originals[name].decode('utf-8-sig').splitlines()
                actual = set()
                generated = False
                for number, line in enumerate(lines, 1):
                    if name == 'setup_windows.bat' and line == ':create_uninstaller':
                        generated = True
                    elif generated and line == ') > "Remove_OptiScaler.bat"':
                        generated = False
                    candidate = line
                    if generated:
                        if not line.startswith('echo '):
                            continue
                        candidate = line[5:]
                    if re.match(r'^\s*@?echo (?:on|off)$', candidate):
                        continue
                    try:
                        display = module._parts(candidate, name)[1]
                    except RuntimeError:
                        continue
                    if re.search('[A-Za-z]', display):
                        actual.add(number)
                translated = {entry['line'] for entry in record['entries']}
                retained = {entry['line'] for entry in record['preserved_entries']}
                self.assertFalse(translated & retained)
                self.assertEqual(actual, translated | retained, name)
                pauses = len(re.findall(r'^[ \t]*(?:echo )?pause$', '\n'.join(lines), re.M))
                self.assertEqual((len(actual), len(translated), len(retained), pauses), expected[name])
                self.assertTrue(record['preserved_english_reason'])
                for entry in record['entries']:
                    self.assertRegex(module._parts(entry['translation'], name)[1], '[\u4e00-\u9fff]')
                for entry in record['preserved_entries']:
                    self.assertEqual(lines[entry['line'] - 1], entry['source'])
                    self.assertTrue(entry['reason'])
                self.assertEqual(record['packaged'], name != 'Streamlined_fetcher_windows.bat')

    def test_batch_codepage_restored_on_each_original_exit_and_before_self_delete(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            module.patch_installer_scripts(root)
            for name, exits in (('setup_windows.bat', 1), ('Streamlined_fetcher_windows.bat', 3)):
                output = (root / name).read_text(encoding='utf-8')
                self.assertEqual(len(re.findall(r'^exit /b [01]$', output, re.M)), exits)
                self.assertEqual(len(re.findall(r'^chcp %_F5_CN_OLD_CP% >nul\nexit /b [01]$', output, re.M)), exits)
            setup = (root / 'setup_windows.bat').read_text(encoding='utf-8')
            generated = setup.split(':create_uninstaller\n', 1)[1]
            self.assertIn("%%%%C in ^('chcp'^)", generated)
            self.assertIn('echo chcp 65001 ^>nul', generated)
            self.assertLess(generated.index('echo chcp %%_F5_CN_OLD_CP%% ^>nul'),
                            generated.index('echo     del "%%~nx0"'))
            self.assertIn('echo pause ^>nul', generated)

    def test_catalog_rejects_control_or_expansion_injection(self):
        module = self.module()
        examples = (
            ('setup_windows.bat', 'echo Hello', 'echo 你好\ndel *'),
            ('setup_windows.bat', 'echo Hello', 'echo 你好 %0'),
            ('setup_windows.bat', 'echo Hello', 'echo 你好 !UNEXPECTED!'),
            ('setup_windows.bat', 'echo Hello', 'echo 你好 & dir'),
            ('get_streamline.ps1', 'Write-Host "Hello"', 'Write-Host "你好 $Unexpected"'),
            ('setup_linux.sh', 'echo "Hello"', 'echo "你好 $(touch unexpected)"'),
        )
        for name, source, translated in examples:
            with self.subTest(name=name, translated=translated):
                with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                    module._validate_entry({'line': 1, 'source': source,
                                            'translation': translated}, name)

    def test_bash_help_and_generated_uninstaller_help_are_safe_and_chinese(self):
        module = self.module()
        bash = find_bash_executable()
        if not bash:
            self.skipTest('Git for Windows Bash unavailable' if os.name == 'nt' else 'Native Bash unavailable')
        try:
            probe = subprocess.run([bash, '--noprofile', '--norc', '-c', 'printf BASH_READY'],
                                   capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest(f'Bash runtime unavailable at {bash}: {exc}')
        if probe.returncode != 0 or probe.stdout != b'BASH_READY':
            self.skipTest(f'Bash runtime unavailable at {bash}: exit={probe.returncode}, stderr={probe.stderr!r}')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            module.patch_installer_scripts(root)
            source = (root / 'setup_linux.sh').read_text(encoding='utf-8')
            uninstaller = source.split("<< 'EOF'\n", 1)[1].split('\nEOF\n', 1)[0] + '\n'
            (root / 'remove_optiscaler.sh').write_bytes(uninstaller.encode('utf-8'))
            for name in ('setup_linux.sh', 'remove_optiscaler.sh'):
                # MSYS resolves a basename from cwd; a raw C:\... argument is
                # not a POSIX path and must not be handed to bash.
                subprocess.run([bash, '--noprofile', '--norc', '-n', name], cwd=root,
                               check=True, capture_output=True, timeout=10)
                result = subprocess.run([bash, '--noprofile', '--norc', name, '--help'], cwd=root,
                                        capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('用法', result.stdout)
                self.assertIn('--help', result.stdout)
            self.assertTrue((root / 'setup_windows.bat').is_file())
            self.assertFalse((root / 'OptiScaler').exists())

    @unittest.skipUnless(os.name == 'nt' and shutil.which('cmd.exe'), 'Windows cmd.exe unavailable')
    def test_windows_codepage_support_in_harmless_fixtures(self):
        module = self.module()
        # Execute only artificial echo/chcp/exit fixtures, never installer bodies.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            safe = '@echo off\n' + module.BATCH_PROLOGUE + 'echo 中文提示\n' + module.BATCH_RESTORE + 'exit /b 7\n'
            (root / 'safe.bat').write_bytes(module._encode(safe, 'safe.bat'))
            emitter = ('@echo off\n' + module.BATCH_PROLOGUE +
                       'setlocal DisableDelayedExpansion\n(\necho @echo off\n'
                       'echo setlocal EnableDelayedExpansion\n' + module.GENERATED_PROLOGUE +
                       'echo echo 中文提示\n' + module.GENERATED_RESTORE +
                       'echo exit /b 7\n) > safe_generated.bat\n' +
                       module.BATCH_RESTORE + 'exit /b 0\n')
            (root / 'emit.bat').write_bytes(module._encode(emitter, 'emit.bat'))
            subprocess.run(['cmd.exe', '/d', '/c', 'emit.bat'], cwd=root, check=True,
                           capture_output=True, timeout=10)
            generated = (root / 'safe_generated.bat').read_text(encoding='utf-8')
            self.assertIn("%%C in ('chcp')", generated)
            self.assertIn('chcp %_F5_CN_OLD_CP% >nul', generated)
            for page in (437, 936, 65001):
                for name in ('safe.bat', 'safe_generated.bat'):
                    driver = ('@echo off\nsetlocal\n'
                              'for /f "tokens=2 delims=:" %%C in (\'chcp\') do set "OLD=%%C"\n'
                              f'chcp {page} >nul\ncall {name}\nset "RC=%errorlevel%"\n'
                              'for /f "tokens=2 delims=:" %%C in (\'chcp\') do echo CP=%%C\n'
                              'echo RC=%RC%\nchcp %OLD% >nul\nexit /b 0\n')
                    (root / 'driver.bat').write_bytes(module._encode(driver, 'driver.bat'))
                    result = subprocess.run(['cmd.exe', '/d', '/c', 'driver.bat'], cwd=root,
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = result.stdout.decode('utf-8')
                    self.assertIn('中文提示', output)
                    self.assertRegex(output, rf'CP=\s*{page}')
                    self.assertIn('RC=7', output)

    def test_powershell_parser_and_license_refusal_when_available(self):
        executable = shutil.which('powershell.exe') or shutil.which('pwsh')
        if not executable:
            self.skipTest('PowerShell unavailable; parser and refusal smoke require Windows CI')
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.checkout(root)
            module.patch_installer_scripts(root)
            script = str(root / 'get_streamline.ps1').replace("'", "''")
            destination = str(root / 'never-created' / 'streamline').replace("'", "''")
            command = ("$ErrorActionPreference='Stop'; $t=$null; $e=$null; "
                       f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$t,[ref]$e); "
                       "if ($e.Count) { throw ($e | Out-String) }; "
                       f"try {{ & '{script}' -Destination '{destination}'; throw 'Expected refusal' }} "
                       "catch { if ($_.Exception.Message -notlike '*-AcceptNvidiaLicenses*') { throw }; "
                       "Write-Output 'LICENSE_REFUSAL_OK' }")
            result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-Command', command],
                                    cwd=root, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'LICENSE_REFUSAL_OK', result.stdout)
            self.assertFalse((root / 'never-created').exists())
            self.assertFalse((root / '.dependencies').exists())


if __name__ == '__main__':
    unittest.main()
