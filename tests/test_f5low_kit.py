"""F5Low release safety probes. Fixtures are inert bytes, never loaded as DLLs."""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.find_spec('f5low_kit')
kit = __import__('f5low_kit') if SPEC else None

FILES = {
    'f5low.dll': b'inert F5Low fixture',
    'libxess_fg.dll': b'inert Intel fixture',
    'LICENSE': b'GPL-3.0 with linking exception fixture',
    'XeSS_LICENSE.txt': b'Intel licence fixture',
    'zstd_LICENSE.txt': b'zstd licence fixture',
    'README-KIT.txt': b'Source: https://github.com/janblade/f5low-fg (commit 1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a)',
}
FILES['kit_hashes.txt'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in FILES.items()).encode()
MAPPING = {
    'f5low.dll': 'OptiScaler/plugins/f5low.dll',
    'libxess_fg.dll': 'OptiScaler/libxess_fg.dll',
    'LICENSE': 'Licenses/f5low_LICENSE.txt',
    'XeSS_LICENSE.txt': 'Licenses/XeSS_LICENSE.txt',
    'zstd_LICENSE.txt': 'Licenses/f5low_zstd_LICENSE.txt',
    'README-KIT.txt': 'Licenses/f5low_README-KIT.txt',
    'kit_hashes.txt': 'Licenses/f5low_kit_hashes.txt',
}
INI = b'; unchanged comments\r\n[FrameGen]\r\nFGOutput=auto\r\nEnabled=auto\r\n[F5Low]\r\nFrameGenerator=auto\r\n[Log]\r\nLogToFile=auto\r\n'
FINAL_INI = b'; unchanged comments\r\n[FrameGen]\r\nFGOutput=f5low\r\nEnabled=auto\r\n[F5Low]\r\nFrameGenerator=xefg_tensor\r\n[Log]\r\nLogToFile=auto\r\n'


class F5LowKitTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(kit, 'F5Low must be included and verified through f5low_kit.py')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make_zip(self, files=None, name='kit.zip'):
        path = self.root / name
        with warnings.catch_warnings(), zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            warnings.simplefilter('ignore', UserWarning)
            for filename, data in (FILES if files is None else files).items():
                info = filename if isinstance(filename, zipfile.ZipInfo) else zipfile.ZipInfo(filename)
                archive.writestr(info, data)
        return path

    def fixture_pins(self, path):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(kit, 'KIT_SHA256', hashlib.sha256(path.read_bytes()).hexdigest()))
        stack.enter_context(mock.patch.object(kit, 'FILE_SHA256', {name: hashlib.sha256(data).hexdigest() for name, data in FILES.items()}))
        stack.enter_context(mock.patch.object(kit, 'FILE_SIZES', {name: len(data) for name, data in FILES.items()}))
        return stack

    def make_stage(self, with_hashes=False):
        stage = self.root / 'stage'
        stage.mkdir()
        for name, destination in MAPPING.items():
            if name == 'kit_hashes.txt' and not with_hashes:
                continue
            path = stage / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(FILES[name])
        (stage / 'OptiScaler.ini').write_bytes(INI)
        return stage

    def test_exact_kit_is_accepted_and_all_seven_files_are_retained(self):
        path = self.make_zip()
        with self.fixture_pins(path):
            files, metadata = kit.read_verified_kit(path)
        self.assertEqual(files, FILES)
        self.assertEqual(metadata['version'], '1.1.0.140')
        self.assertEqual(metadata['source_commit'], '1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a')
        self.assertEqual({entry['path'] for entry in metadata['files']}, set(FILES))

    def test_archive_hash_is_not_taken_from_its_own_manifest(self):
        path = self.make_zip()
        with self.assertRaisesRegex(ValueError, 'archive SHA256'):
            kit.read_verified_kit(path)

    def test_missing_unknown_case_duplicate_and_path_payloads_are_rejected(self):
        cases = [
            *[{key: value for key, value in FILES.items() if key != missing} for missing in FILES],
            {**FILES, 'unknown.dll': b'x'},
            {**FILES, 'F5LOW.DLL': b'x'},
            {**FILES, '../escape': b'x'},
            {**FILES, 'dir\\escape': b'x'},
            {**FILES, 'C:/escape': b'x'},
            {**FILES, 'LICENSE ': b'x'},
            {**FILES, zipfile.ZipInfo('f5low.dll'): b'duplicate'},
        ]
        linked = zipfile.ZipInfo('f5low.dll')
        linked.create_system = 3
        linked.external_attr = (0o120777 << 16)
        cases.append({**{key: value for key, value in FILES.items() if key != 'f5low.dll'}, linked: b'target'})
        for index, files in enumerate(cases):
            with self.subTest(index=index):
                path = self.make_zip(files, f'{index}.zip')
                with self.fixture_pins(path), self.assertRaises(ValueError):
                    kit.read_verified_kit(path)

    def test_payload_size_and_hash_must_match_fixed_release(self):
        for data in [b'x', b'X' * len(FILES['f5low.dll'])]:
            path = self.make_zip({**FILES, 'f5low.dll': data})
            with self.fixture_pins(path), self.assertRaises(ValueError):
                kit.read_verified_kit(path)

    def test_staging_preserves_licences_and_changes_only_two_auto_values(self):
        path = self.make_zip()
        stage = self.make_stage()
        with self.fixture_pins(path):
            manifest = kit.finalize_stage(stage, path)
            metadata = {'f5low_kit_included': True, 'f5low_kit': manifest}
            (stage / 'BUILD-INFO.CN.json').write_text(json.dumps(metadata))
            kit.verify_staged_f5low(stage, metadata)
        self.assertEqual((stage / 'OptiScaler.ini').read_bytes(), FINAL_INI)
        for name, destination in MAPPING.items():
            self.assertEqual((stage / destination).read_bytes(), FILES[name])

    def test_ini_refuses_non_auto_duplicate_missing_or_wrong_section_without_writing(self):
        invalids = [INI.replace(b'FGOutput=auto', b'FGOutput=other'),
                    INI.replace(b'FrameGenerator=auto', b'FrameGenerator=xefg_tensor'),
                    INI + b'\r\nFGOutput=auto\r\n',
                    INI.replace(b'FGOutput=auto\r\n', b''),
                    INI.replace(b'[FrameGen]', b'[Other]'),
                    INI.replace(b'FGOutput=auto', b'FGOutput =auto'),
                    INI + b'\r\n[FrameGen]\r\n',
                    INI + b'\r\nfgoutput=auto\r\n']
        for data in invalids:
            with self.subTest(data=data), self.assertRaises(ValueError):
                kit.apply_release_defaults(data)

    def test_final_stage_refuses_unverified_existing_bytes_without_partial_changes(self):
        path = self.make_zip()
        stage = self.make_stage()
        (stage / MAPPING['LICENSE']).write_bytes(b'missing linking exception')
        with self.fixture_pins(path), self.assertRaises(ValueError):
            kit.finalize_stage(stage, path)
        self.assertEqual((stage / 'OptiScaler.ini').read_bytes(), INI)
        self.assertFalse((stage / MAPPING['kit_hashes.txt']).exists())

    def test_public_archive_rechecks_pins_defaults_and_metadata_instead_of_self_report(self):
        path = self.make_zip()
        stage = self.make_stage()
        with self.fixture_pins(path):
            manifest = kit.finalize_stage(stage, path)
            metadata = {'f5low_kit_included': True, 'f5low_kit': manifest}
            (stage / 'BUILD-INFO.CN.json').write_text(json.dumps(metadata))
            payloads = {p.relative_to(stage).as_posix(): p.read_bytes() for p in stage.rglob('*') if p.is_file()}
            final_zip = self.make_zip(payloads, 'release.zip')
            kit.verify_package_f5low(final_zip, metadata)
            changes = [
                {**payloads, MAPPING['f5low.dll']: b'changed'},
                {**payloads, MAPPING['libxess_fg.dll']: b'old Intel DLL'},
                {**payloads, 'OptiScaler.ini': INI},
                {**payloads, 'wrong/f5low.dll': FILES['f5low.dll']},
                {**payloads, 'wrong/libxess_fg.dll': FILES['libxess_fg.dll']},
                {**payloads, 'OptiScaler/plugins/unknown.dll': b'unknown'},
                {**payloads, 'BUILD-INFO.CN.json': b'{"f5low_kit_included": false}'},
            ]
            for missing in MAPPING.values():
                changes.append({name: data for name, data in payloads.items() if name != missing})
            for notice in ('LICENSE', 'XeSS_LICENSE.txt', 'zstd_LICENSE.txt', 'README-KIT.txt', 'kit_hashes.txt'):
                changes.append({**payloads, MAPPING[notice]: b'tampered licence or attribution'})
            for changed in changes:
                final_zip = self.make_zip(changed, 'bad-release.zip')
                with self.assertRaises(ValueError):
                    kit.verify_package_f5low(final_zip, metadata)
            for wrong in [False, 1, 'true']:
                with self.assertRaises(ValueError):
                    kit.verify_package_f5low(self.make_zip(payloads, 'release.zip'), {**metadata, 'f5low_kit_included': wrong})
            for key, value in [('version', 'invented'), ('source_commit', 'a' * 40),
                               ('archive_url', 'https://example.invalid/kit.zip'),
                               ('archive_sha256', 'b' * 64), ('intel_version', '1.3.1.78')]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    kit.verify_package_f5low(self.make_zip(payloads, 'release.zip'), {**metadata, 'f5low_kit': {**manifest, key: value}})

    def test_real_upstream_ini_changes_no_other_byte_or_setting(self):
        source = ROOT / '_upstream/OptiScaler.ini'
        if not source.is_file():
            self.skipTest('Pristine upstream fixture unavailable')
        original = source.read_bytes()
        expected = original.replace(b'\nFGOutput=auto', b'\nFGOutput=f5low', 1).replace(
            b'\nFrameGenerator=auto', b'\nFrameGenerator=xefg_tensor', 1)
        self.assertEqual(kit.apply_release_defaults(original), expected)

    def test_linked_stage_inputs_are_rejected_without_modifying_external_files(self):
        path = self.make_zip()
        stage = self.make_stage()
        linked = stage / MAPPING['LICENSE']
        linked.unlink()
        external = self.root / 'external-licence'
        external.write_bytes(FILES['LICENSE'])
        try:
            linked.symlink_to(external)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        with self.fixture_pins(path), self.assertRaises(ValueError):
            kit.finalize_stage(stage, path)
        self.assertEqual(external.read_bytes(), FILES['LICENSE'])
        self.assertEqual((stage / 'OptiScaler.ini').read_bytes(), INI)

    def test_official_download_when_available_is_checked_without_executing_dlls(self):
        archive = os.environ.get('F5LOW_KIT_ZIP')
        if not archive:
            self.skipTest('Optional official-kit integration fixture not supplied')
        files, metadata = kit.read_verified_kit(Path(archive))
        self.assertEqual(hashlib.sha256(files['f5low.dll']).hexdigest(), '0993352a97a05537a88bd1d0266cb62ae581f219b75fc588fbc15eeeacb48fa4')
        self.assertEqual(metadata['archive_sha256'], '97fa6fb53a2278dfc651e4de2b2201f399f40ce49474b5f8199a2e5794d87f56')


if __name__ == '__main__':
    unittest.main()
