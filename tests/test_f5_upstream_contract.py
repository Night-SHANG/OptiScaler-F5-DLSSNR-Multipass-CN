"""Real-Git regression tests for fail-closed automatic upstream compatibility."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import os

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'tools/f5_upstream_contract.py'
REPOSITORY = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'
BASELINE = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.STDOUT).decode().strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert MODULE.is_file(), 'The fail-closed upstream compatibility validator is not implemented'
        spec = importlib.util.spec_from_file_location('f5_upstream_contract', MODULE)
        cls.contract_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.contract_module)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, 'init', '-b', 'main')
        git(self.root, 'remote', 'add', 'origin', REPOSITORY)
        self.files = {
            'src/menu.cpp': b'#include "ui.h"\nvoid draw() { ImGui::Text("Ready"); }\n',
            'src/ui.h': b'#pragma once\nvoid draw();\n',
            'src/engine.cpp': b'int run() { return 1; }\n',
            'package_release.ps1': b'Write-Output "package"\n',
            'LICENSE': b'Fixture license\n',
            '.gitmodules': b'[submodule "dep"]\n\tpath = external/dep\n\turl = https://github.com/example/dep.git\n',
            'assets/dependency.dll': b'MZfixture\0binary',
            'README.md': b'Fixture documentation\n',
        }
        for name, data in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git(self.root, 'add', '.')
        self.gitlink = '1' * 40
        git(self.root, 'update-index', '--add', '--cacheinfo', f'160000,{self.gitlink},external/dep')
        self.baseline = self.commit()
        self.contract = {
            'schema': 1, 'repository': REPOSITORY, 'branch': 'main', 'baseline_commit': self.baseline,
            'normalizer': 'cpp-structure-v1',
            'source_paths': ['src/engine.cpp', 'src/menu.cpp', 'src/ui.h'],
            'protected_files': {name: {'mode': '100644', 'sha256': digest(data)}
                                for name, data in self.files.items() if name not in ('src/menu.cpp', 'README.md')},
            'audited_sources': {'src/menu.cpp': {'mode': '100644', 'sha256': digest(self.files['src/menu.cpp']),
                'structure_sha256': self.contract_module.cpp_structure_sha256(self.files['src/menu.cpp']),
                'literal_count': 1, 'mutable_literal_ordinals': [0],
                'literal_sha256': self.contract_module.cpp_literal_sha256(self.files['src/menu.cpp'], [0])}},
            'gitlinks': {'external/dep': self.gitlink},
        }
        self.cfg = {'repository': REPOSITORY, 'branch': 'main', 'commit': self.baseline, 'upstream_version': 'v0.1.32'}

    def commit(self):
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'fixture')
        return git(self.root, 'rev-parse', 'HEAD')

    def test_git_root_uses_filesystem_identity_not_path_spelling(self):
        same = self.contract_module.same_worktree_root
        self.assertTrue(same(self.root.as_posix(), self.root))
        self.assertFalse(same(str(self.root / 'absent'), self.root))
        with tempfile.TemporaryDirectory() as other:
            self.assertFalse(same(other, self.root))
        # Git for Windows uses '/', pathlib uses '\\'; native samefile must
        # resolve separators, case and 8.3 aliases without text normalization.
        with mock.patch.object(self.contract_module.os.path, 'samefile', return_value=True) as native:
            self.assertTrue(same('D:/a/Source Root', r'd:\a\SOURCE ROOT'))
            native.assert_called_once_with('D:/a/Source Root', r'd:\a\SOURCE ROOT')
        if os.name == 'nt':
            self.assertTrue(same(str(self.root).swapcase(), self.root))
            import ctypes
            buffer = ctypes.create_unicode_buffer(32768)
            count = ctypes.windll.kernel32.GetShortPathNameW(str(self.root), buffer, len(buffer))
            self.assertGreater(count, 0)
            self.assertLess(count, len(buffer))
            self.assertTrue(same(buffer.value, self.root))

    def change(self, name, data=None):
        path = self.root / name
        if data is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git(self.root, 'add', '--', name)
        self.cfg['commit'] = self.commit()

    def verify(self):
        return self.contract_module.verify_source(self.root, self.cfg, self.contract)

    def test_baseline_passes_without_initialized_submodule(self):
        before = git(self.root, 'status', '--porcelain')
        result = self.verify()
        self.assertTrue(result['compatible'])
        self.assertEqual(result['commit'], self.baseline)
        self.assertEqual(result['baseline_commit'], self.baseline)
        self.assertEqual(before, git(self.root, 'status', '--porcelain'))
        self.assertFalse((self.root / 'external/dep/.git').exists())

    def test_source_literals_and_spacing_can_change(self):
        self.change('src/menu.cpp', b'#include "ui.h"\nvoid draw( ) { ImGui :: Text ( "Ready now" ); }\n')
        result = self.verify()
        self.assertEqual(result['changed_audited_sources'], ['src/menu.cpp'])
        self.assertTrue(result['compatible'])

    def test_candidate_git_objects_are_checked_before_checkout(self):
        self.change('src/menu.cpp', b'#include "ui.h"\nvoid draw() { ImGui::Text("New label"); }\n')
        candidate = self.cfg['commit']
        git(self.root, 'checkout', '--detach', self.baseline)
        with self.assertRaisesRegex(ValueError, 'HEAD'):
            self.verify()
        result = self.contract_module.verify_source(self.root, self.cfg, self.contract, verify_worktree=False)
        self.assertEqual(result['commit'], candidate)
        self.assertFalse(result['verified_worktree'])
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.baseline)

    def test_protected_script_license_binary_and_dependency_changes_fail(self):
        for name in ('package_release.ps1', 'LICENSE', '.gitmodules', 'assets/dependency.dll'):
            with self.subTest(name=name):
                git(self.root, 'reset', '--hard', self.baseline)
                self.change(name, self.files[name] + b'changed')
                with self.assertRaisesRegex(ValueError, 'protected'):
                    self.verify()

    def test_new_or_deleted_protected_inputs_fail(self):
        for name in ('new.ps1', 'helper.py', 'tool.cmake', 'new.props', 'NOTICE-new.md', 'LICENSE.md', 'assets/new.dll', 'data/config.json'):
            with self.subTest(name=name):
                git(self.root, 'reset', '--hard', self.baseline)
                self.change(name, b'new input')
                with self.assertRaisesRegex(ValueError, 'protected'):
                    self.verify()
        git(self.root, 'reset', '--hard', self.baseline)
        self.change('LICENSE')
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.verify()

    def test_gitlink_addition_deletion_and_revision_changes_fail(self):
        for args in [('--cacheinfo', f'160000,{"2" * 40},external/dep'),
                     ('--add', '--cacheinfo', f'160000,{"2" * 40},external/new'),
                     ('--force-remove', 'external/dep')]:
            with self.subTest(args=args):
                git(self.root, 'reset', '--hard', self.baseline)
                git(self.root, 'update-index', *args)
                self.cfg['commit'] = self.commit()
                with self.assertRaisesRegex(ValueError, 'gitlink'):
                    self.verify()

    def test_changed_ui_structure_fails(self):
        self.change('src/menu.cpp', self.files['src/menu.cpp'].replace(b'ImGui::Text', b'ImGui::Button'))
        with self.assertRaisesRegex(ValueError, 'structure'):
            self.verify()

    def test_only_reviewed_literal_ordinals_can_change(self):
        source = b'#include "ui.h"\nvoid draw() { load("safe.dll"); ImGui::Text("Ready"); shader("mov r0, r1"); }\n'
        self.change('src/menu.cpp', source)
        self.contract['baseline_commit'] = self.cfg['commit']
        record = self.contract['audited_sources']['src/menu.cpp']
        record.update(sha256=digest(source), structure_sha256=self.contract_module.cpp_structure_sha256(source),
                      literal_count=3, mutable_literal_ordinals=[1],
                      literal_sha256=self.contract_module.cpp_literal_sha256(source, [1]))
        baseline = self.cfg['commit']
        for old, new in [(b'safe.dll', b'evil.dll'), (b'mov r0, r1', b'evil code')]:
            with self.subTest(old=old):
                git(self.root, 'reset', '--hard', baseline)
                self.change('src/menu.cpp', source.replace(old, new))
                with self.assertRaisesRegex(ValueError, 'literal'):
                    self.verify()
        git(self.root, 'reset', '--hard', baseline)
        self.change('src/menu.cpp', source.replace(b'Ready', b'New label'))
        self.assertTrue(self.verify()['compatible'])

    def test_mutable_prose_cannot_introduce_format_identity_or_escape_syntax(self):
        for value in (b'%s', b'{}', b'Label##id', b'Label\\x25s'):
            with self.subTest(value=value):
                git(self.root, 'reset', '--hard', self.baseline)
                self.change('src/menu.cpp', self.files['src/menu.cpp'].replace(b'Ready', value))
                with self.assertRaisesRegex(ValueError, 'literal'):
                    self.verify()
        for source in (b'emit("%s");', b'emit("{}");', b'emit("Label##id");', b'emit("Line\\n");'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.contract_module.cpp_literal_sha256(source, [0])

    def test_adjacent_ambiguous_literals_cannot_be_made_mutable(self):
        with self.assertRaisesRegex(ValueError, 'adjacent'):
            self.contract_module.cpp_literal_sha256(b'emit("one" "two");', [0])
        with self.assertRaises(ValueError):
            self.contract_module.cpp_literal_sha256(b'emit("one");', [1])
        with self.assertRaises(ValueError):
            self.contract_module.cpp_literal_sha256(b'emit("one");', [0, 0])

    def test_new_display_bearing_existing_path_fails(self):
        self.change('src/engine.cpp', b'void run() { ImGui::Text("New UI"); }\n')
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.verify()

    def test_new_or_deleted_cpp_paths_fail(self):
        self.change('src/new.cpp', b'void draw_new();\n')
        with self.assertRaisesRegex(ValueError, 'source path'):
            self.verify()
        git(self.root, 'reset', '--hard', self.baseline)
        self.change('src/menu.cpp')
        with self.assertRaisesRegex(ValueError, 'source path'):
            self.verify()

    def test_include_directive_and_character_literal_changes_fail(self):
        for changed in (b'#include "other.h"\nvoid draw() { ImGui::Text("Ready"); }\n',
                        b'#include "ui.h"\nvoid draw() { ImGui::Text(L"Ready"); }\n'):
            with self.subTest(changed=changed):
                git(self.root, 'reset', '--hard', self.baseline)
                self.change('src/menu.cpp', changed)
                with self.assertRaisesRegex(ValueError, 'structure'):
                    self.verify()
        normalize = self.contract_module.cpp_structure_sha256
        self.assertNotEqual(normalize(b"int n = 'a';"), normalize(b"int n = 'b';"))
        self.assertNotEqual(normalize(b'#define X a\nb;'), normalize(b'#define X a b;'))
        self.assertNotEqual(normalize(b'int x;'), normalize(b'intx;'))
        self.assertNotEqual(normalize(b'x + +y;'), normalize(b'x ++y;'))

    def test_normalizer_supports_raw_escaped_and_prefixed_strings(self):
        normalize = self.contract_module.cpp_structure_sha256
        self.assertEqual(normalize(b'emit(u8R"tag(a " // text)tag", "a\\\"b");'),
                         normalize(b'emit(u8R"other(different)other", "new");'))
        self.assertNotEqual(normalize(b'emit("x");'), normalize(b'emit("x"_suffix);'))
        self.assertNotEqual(normalize(b'1e+2;'), normalize(b'1e + 2;'))
        self.assertNotEqual(normalize(b'#define NAME "one"\n'), normalize(b'#define NAME "two"\n'))
        for data in (b'"unterminated', b'/* unterminated', b'R"bad(missing', b'int \xff;'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                normalize(data)

    def test_preprocessor_macro_whitespace_and_line_splicing_stay_semantic(self):
        normalize = self.contract_module.cpp_structure_sha256
        self.assertNotEqual(normalize(b'#define F(x) x\n'), normalize(b'#define F (x) x\n'))
        self.assertEqual(normalize(b'int ab;'), normalize(b'int a\\\nb;'))
        self.assertNotEqual(normalize(b'// comment\\\nint active;\n'), normalize(b'// comment\nint active;\n'))

    def test_block_comment_newlines_do_not_end_preprocessor_directives(self):
        normalize = self.contract_module.cpp_structure_sha256
        self.assertNotEqual(normalize(b'#define X\nint y;\n'), normalize(b'#define X/*\n*/int y;\n'))
        self.assertNotEqual(normalize(b'#define X int y;\n'), normalize(b'#define X/*\n*/int y;\n'))
        self.assertNotEqual(normalize(b'int x;\n#define Y 1\n'), normalize(b'int x;/*\n*/#define Y 1\n'))

    def test_comments_and_attribution_positions_are_immutable(self):
        normalize = self.contract_module.cpp_structure_sha256
        self.assertNotEqual(normalize(b'// Copyright Example\nint x;'), normalize(b'int x;'))
        self.assertNotEqual(normalize(b'// Original credit\nint x;'), normalize(b'// Different credit\nint x;'))
        self.assertNotEqual(normalize(b'/* note */ int x;'), normalize(b'int /* note */ x;'))
        self.assertEqual(normalize(b'/* note */ int x;'), normalize(b'  /* note */   int  x ;\n'))
        self.change('src/menu.cpp', b'// Additional upstream comment\n' + self.files['src/menu.cpp'])
        with self.assertRaisesRegex(ValueError, 'structure'):
            self.verify()

    def test_unsafe_windows_paths_fail_before_checkout(self):
        blob = git(self.root, 'rev-parse', 'HEAD:README.md')
        baseline_tree = git(self.root, 'rev-parse', self.baseline + '^{tree}')
        before_index = git(self.root, 'ls-files', '-s')
        before_status = git(self.root, 'status', '--porcelain')

        def object_tree_with_path(tree, components):
            # Build only Git objects, never unsafe index/worktree paths. Git for
            # Windows correctly rejects CON/aux/? during update-index already,
            # which would prevent testing our independent pre-checkout gate.
            entries = {}
            if tree:
                raw = subprocess.check_output(['git', 'ls-tree', '-z', tree], cwd=self.root)
                for entry in raw.split(b'\0'):
                    if not entry:
                        continue
                    metadata, name = entry.split(b'\t', 1)
                    mode, _, oid = metadata.decode('ascii').split()
                    entries[name] = (mode, oid)
            name = components[0].encode('utf-8')
            if len(components) == 1:
                entries[name] = ('100644', blob)
            else:
                child = entries.get(name, (None, None))[1]
                entries[name] = ('040000', object_tree_with_path(child, components[1:]))
            ordered = sorted(entries, key=lambda name: name + (b'/' if entries[name][0] == '040000' else b''))
            raw = b''.join(
                f'{int(entries[name][0], 8):o} '.encode('ascii') + name + b'\0'
                + bytes.fromhex(entries[name][1]) for name in ordered)
            return subprocess.check_output(
                ['git', 'hash-object', '-t', 'tree', '-w', '--stdin'],
                input=raw, cwd=self.root).decode().strip()

        for name in ('docs/CON.md', 'docs/bad?.md', 'docs/aux/guide.md'):
            with self.subTest(name=name):
                tree = object_tree_with_path(baseline_tree, name.split('/'))
                self.cfg['commit'] = git(
                    self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit-tree', tree, '-p', self.baseline, '-m', 'unsafe path object fixture')
                with self.assertRaisesRegex(ValueError, 'path'):
                    self.contract_module.verify_source(self.root, self.cfg, self.contract, verify_worktree=False)
                self.assertEqual(git(self.root, 'ls-files', '-s'), before_index)
                self.assertEqual(git(self.root, 'status', '--porcelain'), before_status)
                self.assertFalse((self.root / 'docs').exists())

    def test_nonmutable_raw_string_preserves_physical_line_splices(self):
        literal_digest = self.contract_module.cpp_literal_sha256
        self.assertNotEqual(literal_digest(b'emit(R"(a\\\nb)");', []), literal_digest(b'emit(R"(ab)");', []))
        self.assertNotEqual(literal_digest(b'emit("a\\\nb");', []), literal_digest(b'emit("ab");', []))

    def test_mode_change_and_symlink_fail(self):
        git(self.root, 'update-index', '--chmod=+x', 'src/menu.cpp')
        self.cfg['commit'] = self.commit()
        with self.assertRaisesRegex(ValueError, 'mode'):
            self.verify()
        git(self.root, 'reset', '--hard', self.baseline)
        blob = subprocess.check_output(['git', 'hash-object', '-w', '--stdin'], input=b'/tmp/escape', cwd=self.root).decode().strip()
        git(self.root, 'update-index', '--add', '--cacheinfo', f'120000,{blob},new-link')
        self.cfg['commit'] = self.commit()
        with self.assertRaisesRegex(ValueError, 'mode|symlink'):
            self.verify()

    def test_dirty_index_tracked_and_ignored_untracked_files_fail(self):
        path = self.root / 'src/menu.cpp'
        path.write_bytes(path.read_bytes() + b'// uncommitted change\n')
        with self.assertRaisesRegex(ValueError, 'worktree'):
            self.verify()
        git(self.root, 'add', 'src/menu.cpp')
        with self.assertRaisesRegex(ValueError, 'index'):
            self.verify()
        git(self.root, 'reset', '--hard', self.baseline)
        (self.root / '.git/info/exclude').write_text('untracked.props\n')
        (self.root / 'untracked.props').write_bytes(b'malicious ignored build input')
        with self.assertRaisesRegex(ValueError, 'untracked'):
            self.verify()

    def test_managed_marker_requires_exact_current_identity_and_regular_file(self):
        marker = self.root / '.f5-cn-managed.json'
        owner = {'schema': 1, 'root': str(self.root.resolve().parent), 'repository': REPOSITORY, 'commit': self.cfg['commit']}
        marker.write_text(json.dumps(owner))
        self.assertTrue(self.verify()['compatible'])
        for change in ({'commit': '0' * 40}, {'extra': True}, {'schema': True}, {'root': '/unrelated'}):
            marker.write_text(json.dumps({**owner, **change}))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'marker'):
                self.verify()
        marker.unlink()
        marker.symlink_to(self.root / 'README.md')
        with self.assertRaisesRegex(ValueError, 'marker'):
            self.verify()

    def test_documentation_changes_are_allowed_but_hidden_or_license_docs_are_not(self):
        self.change('README.md', b'Updated documentation')
        self.change('docs/guide.md', b'New documentation')
        self.assertTrue(self.verify()['compatible'])
        self.change('.github/actions/tool/README.md', b'New hidden build input')
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.verify()

    def test_invalid_repository_branch_sha_or_version_fails(self):
        validate = self.contract_module.validate_config
        validate(self.cfg, self.contract)
        for key, value in [('repository', 'https://evil.invalid/repo.git'), ('branch', 'other'),
                           ('commit', 'main'), ('commit', 'a' * 39), ('commit', 'A' * 40), ('commit', '--help'),
                           ('upstream_version', '../escape'), ('upstream_version', 'v1.2.3;whoami'),
                           ('upstream_version', 'v1.2'), ('upstream_version', 'main-' + '0' * 12),
                           ('upstream_version', 'v1.2.3\n')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate({**self.cfg, key: value}, self.contract)
        for version in ('v1.2.3', 'v1.2.3-rc.1', 'main-' + self.baseline[:12]):
            validate({**self.cfg, 'upstream_version': version}, self.contract)

    def test_missing_or_noncommit_object_fails(self):
        for oid in ('f' * 40, git(self.root, 'rev-parse', 'HEAD:README.md'), git(self.root, 'rev-parse', 'HEAD^{tree}')):
            with self.subTest(oid=oid), self.assertRaises(ValueError):
                self.contract_module.verify_source(self.root, {**self.cfg, 'commit': oid}, self.contract)

    @unittest.skipIf(__import__('os').name == 'nt', 'POSIX helper probe; production protocol denial is cross-platform')
    def test_missing_promisor_blob_never_runs_remote_helper(self):
        # A partial clone would otherwise lazily fetch via a configured helper.
        sentinel = self.root / '.git/helper-ran'
        helper = self.root / '.git/untrusted-helper'
        helper.write_text('#!/bin/sh\ntouch "' + str(sentinel) + '"\nexit 1\n')
        helper.chmod(0o755)
        git(self.root, 'config', 'extensions.partialClone', 'lazy')
        git(self.root, 'config', 'remote.lazy.promisor', 'true')
        git(self.root, 'config', 'remote.lazy.url', 'ext::' + str(helper))
        git(self.root, 'config', 'protocol.ext.allow', 'always')
        oid = git(self.root, 'rev-parse', 'HEAD:assets/dependency.dll')
        (self.root / '.git/objects' / oid[:2] / oid[2:]).unlink()
        with self.assertRaises(ValueError):
            self.verify()
        self.assertFalse(sentinel.exists(), 'Read-only verification executed a lazy-fetch remote helper')

    def test_unapproved_origin_fails_without_fetching(self):
        git(self.root, 'remote', 'set-url', 'origin', 'https://evil.invalid/repo.git')
        with self.assertRaisesRegex(ValueError, 'origin'):
            self.verify()

    def test_load_contract_and_reject_incomplete_or_inconsistent_evidence(self):
        path = self.root / 'contract.json'
        path.write_text(json.dumps(self.contract))
        self.assertEqual(self.contract_module.load_contract(path), self.contract)
        changes = [('schema', 2), ('normalizer', 'unknown'), ('gitlinks', {}), ('source_paths', ['src/menu.cpp']),
                   ('protected_files', {}), ('repository', 'https://evil.invalid/repo.git')]
        for key, value in changes:
            with self.subTest(key=key):
                altered = copy.deepcopy(self.contract)
                altered[key] = value
                path.write_text(json.dumps(altered))
                if key == 'gitlinks':
                    with self.assertRaises(ValueError):
                        self.contract_module.verify_source(self.root, self.cfg, altered)
                else:
                    with self.assertRaises(ValueError):
                        self.contract_module.load_contract(path)
        path.write_text('{"schema": 1, "schema": 1}')
        with self.assertRaises(ValueError):
            self.contract_module.load_contract(path)

    def test_checked_in_contract_preserves_audit_hashes_and_path_sets(self):
        contract = self.contract_module.load_contract(ROOT / 'upstream-contract.json')
        self.assertEqual(contract['baseline_commit'], BASELINE)
        expected = {
            'package_release.ps1': 'ceb7cf129a654591e70f897c0ba410039a94eb626c507fd252584969ff4a5a1c',
            'get_hybrid_assets.ps1': '5fcd0c8018c1030e63e664d5df56e9a757bdafda77df688354cd4527e90172b1',
            'OptiScaler/OptiScaler.vcxproj': '516fb296ea12deab12a2d35a1a96ea1a87955a3bfeb3e2bb1a033b0519c7d774',
        }
        for name, sha in expected.items():
            self.assertEqual(contract['protected_files'][name]['sha256'], sha)
        installers = json.loads((ROOT / 'Localization/installers.zh-CN.json').read_text())
        for record in installers['scripts']:
            self.assertEqual(contract['protected_files'][record['path']]['sha256'], record['source_sha256'])
        redist = installers['redist']
        self.assertEqual(contract['protected_files'][redist['path']]['sha256'], redist['sha256'])
        inventory = json.loads((ROOT / 'reports/coverage-inventory.json').read_text())
        boundaries = json.loads((ROOT / 'reports/display-boundaries.json').read_text())
        audited = set(inventory['source_files']) | {record['file'] for record in boundaries['files']}
        self.assertEqual(set(contract['audited_sources']), audited)
        self.assertIn('OptiScaler/include/imgui/imgui.cpp', contract['protected_files'])
        self.assertIn('OptiScaler/include/imgui/imgui_draw.cpp', contract['protected_files'])
        self.assertEqual(len(contract['gitlinks']), 10)


if __name__ == '__main__':
    unittest.main()
