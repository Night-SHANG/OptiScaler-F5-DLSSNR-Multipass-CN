"""Full release verifier probes with inert F5Low bytes and no external actions."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_synced_release_gate import (
    F5LOW_FILES, F5LOW_INI, NEXT_PIN, NEXT_VERSION, f5low_fixture_policy, future_fixture,
)
from test_test_release_gate import SHA, digest
import f5low_kit
import publish_test_release as core


class F5LowReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = f5low_fixture_policy()
        self.addCleanup(self.policy.close)
        self.block = patch.object(core.subprocess, 'run', side_effect=AssertionError('No external release operation'))
        self.block.start()
        self.addCleanup(self.block.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = future_fixture(Path(self.tmp.name))

    def verify(self):
        return core.verify_artifact(self.fixture.artifacts, SHA, self.fixture.catalog,
                                    upstream=NEXT_PIN, upstream_version=NEXT_VERSION, require_f5low=True)

    def test_complete_pinned_kit_passes_the_entire_verifier(self):
        metadata = self.verify()['metadata']
        self.assertIs(metadata['f5low_kit_included'], True)
        self.assertEqual(metadata['f5low_kit'], f5low_kit.expected_metadata())
        self.assertEqual(metadata['f5low_kit']['intel_version'], '1.3.4.95')
        self.assertEqual(metadata['variant'], 'downloader-only')

    def test_test_fixture_is_rejected_by_unmodified_production_policy(self):
        self.policy.close()
        with self.assertRaisesRegex(core.GateError, 'F5Low'):
            self.verify()

    def test_every_binary_license_and_attribution_file_is_required(self):
        for name, path in f5low_kit.STAGED_PATHS.items():
            with self.subTest(name=name):
                saved = self.fixture.payload.pop(path)
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()
                self.fixture.payload[path] = saved

    def test_f5low_intel_and_all_notices_use_fixed_hashes_not_internal_checksums(self):
        for name, path in f5low_kit.STAGED_PATHS.items():
            with self.subTest(name=name):
                saved = self.fixture.payload[path]
                self.fixture.payload[path] = b'X' * len(saved)
                # Recompute package SHA, sidecar and all self-reported internal hashes.
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low.*SHA256'):
                    self.verify()
                self.fixture.payload[path] = saved

    def test_artifact_cannot_redeclare_tampered_file_hashes_or_sizes(self):
        for name, path in f5low_kit.STAGED_PATHS.items():
            with self.subTest(name=name):
                self.fixture.payload[path] = b'forged data'
                forged = deepcopy(f5low_kit.expected_metadata())
                record = next(item for item in forged['files'] if item['path'] == name)
                record.update(sha256=digest(b'forged data'), size=len(b'forged data'))
                self.fixture.inner['f5low_kit'] = forged
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()
                self.fixture.payload[path] = F5LOW_FILES[name]

    def test_each_file_must_use_its_exact_package_path(self):
        for name, path in f5low_kit.STAGED_PATHS.items():
            with self.subTest(name=name):
                unexpected = 'unexpected/' + name
                self.fixture.payload[unexpected] = self.fixture.payload.pop(path)
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()
                self.fixture.payload[path] = self.fixture.payload.pop(unexpected)

    def test_extra_f5low_dll_or_unknown_plugin_cannot_hide_beside_valid_kit(self):
        for path in ('f5low.dll', 'OptiScaler/f5low.dll', 'nested/F5LOW.DLL',
                     'libxess_fg.dll', 'OptiScaler/plugins/other.dll'):
            with self.subTest(path=path):
                self.fixture.payload[path] = F5LOW_FILES['f5low.dll']
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()
                del self.fixture.payload[path]

    def test_inclusion_flag_must_be_present_and_exactly_boolean_true(self):
        for value in (False, 0, 1, 'true', None):
            with self.subTest(value=value):
                self.fixture.inner['f5low_kit_included'] = value
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()
        del self.fixture.inner['f5low_kit_included']
        self.fixture.write()
        with self.assertRaisesRegex(core.GateError, 'F5Low'):
            self.verify()

    def test_removing_entire_kit_and_metadata_cannot_select_legacy_policy(self):
        for path in f5low_kit.STAGED_PATHS.values():
            del self.fixture.payload[path]
        del self.fixture.inner['f5low_kit_included']
        del self.fixture.inner['f5low_kit']
        self.fixture.write()
        with self.assertRaisesRegex(core.GateError, 'F5Low'):
            self.verify()

    def test_all_source_identity_fields_are_locked_outside_artifact(self):
        for key, value in (
            ('version', '1.1.0.139'), ('archive_url', 'https://example.invalid/f5low.zip'),
            ('archive_sha256', 'd' * 64), ('source_repository', 'https://github.com/other/f5low'),
            ('source_commit', 'd' * 40), ('intel_version', '1.3.1.78'), ('files', []),
        ):
            with self.subTest(key=key):
                self.fixture.inner['f5low_kit'] = {**f5low_kit.expected_metadata(), key: value}
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()

    def test_exact_release_defaults_are_required(self):
        for ini in (
            F5LOW_INI.replace(b'FGOutput=f5low', b'FGOutput=auto'),
            F5LOW_INI.replace(b'FrameGenerator=xefg_tensor', b'FrameGenerator=auto'),
            F5LOW_INI.replace(b'FrameGenerator=xefg_tensor', b'FrameGenerator=intel'),
            F5LOW_INI.replace(b'[F5Low]', b'[Other]'),
            F5LOW_INI + b'FrameGenerator=xefg_tensor\n',
        ):
            with self.subTest(ini=ini):
                self.fixture.payload['OptiScaler.ini'] = ini
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'F5Low'):
                    self.verify()

    def test_f5low_policy_does_not_allow_nvidia_proprietary_payloads(self):
        for name in ('nvngx_dlssnr.dll', 'OptiScaler/nvngx_dlssg.dll',
                     'OptiScaler/streamline/sl.interposer.dll', 'dlssg_sm86.dll'):
            with self.subTest(name=name):
                self.fixture.payload[name] = b'inert forbidden payload'
                self.fixture.write()
                with self.assertRaisesRegex(core.GateError, 'Forbidden downloader-only'):
                    self.verify()
                del self.fixture.payload[name]

    def test_inner_outer_f5low_claims_cannot_diverge(self):
        self.fixture.write(outer_changes={'f5low_kit_included': False})
        with self.assertRaisesRegex(core.GateError, 'Inner/outer'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
