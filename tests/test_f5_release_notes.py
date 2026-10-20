"""Offline tests for computed release progress and bounded body replacement."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
CN_SHA = "a" * 40
UPSTREAM_SHA = "b" * 40
PUBLISHED_CN_SHA = "6c9128d67a8fb5a21303fabb8affd032806ab862"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fixture():
    sources = {"old": "Quality", "new": "Apply", "tech": "GPU", "gone": "Removed"}
    catalog = {
        "schema": 1, "channel": "master", "upstream_commit": UPSTREAM_SHA,
        "entries": {
            key: {"source": source, "source_hash": digest(source),
                  "obsolete": key == "gone", "occurrences": []}
            for key, source in sources.items()
        },
    }
    zh = {
        "locale": "zh-CN",
        "entries": {
            "old": {"text": "质量", "source_hash": digest("Quality"), "state": "reviewed",
                    "note": "exact-source reuse; original state retained"},
            "new": {"text": "应用", "source_hash": digest("Apply"), "state": "machine_translated",
                    "review": {"kind": "AI semantic review"}, "model": "preserved-model"},
            "tech": {"text": "GPU", "source_hash": digest("GPU"), "state": "machine_translated"},
        },
    }
    retained = {
        "upstream_commit": UPSTREAM_SHA,
        "entries": [{"key": "tech", "source": "GPU", "reason": "保留技术名称", "occurrences": []}],
    }
    pending = {
        "locale": "zh-CN",
        "scan": {
            "added": ["new", "new", "tech", "gone", "unknown"],
            "changed": ["new", "old", "unknown"],
            "removed": ["gone", "gone", "unknown"],
        },
        # These stale reports must never override the current catalog/translation.
        "missing": [{"key": "old"}],
        "changed": [{"key": "new"}],
    }
    return catalog, zh, retained, pending


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("f5_release_notes")

    def test_current_active_catalog_is_the_denominator(self):
        stats = self.module.summarize(*fixture())
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["changed_display_translations"], 2)
        self.assertEqual(stats["retained_technical_entries"], 1)
        self.assertEqual(stats["effective"], 3)
        self.assertEqual(stats["missing"], 0)
        self.assertEqual(stats["stale"], 0)
        self.assertEqual(stats["reviewed"], 1)
        self.assertEqual(stats["machine_translated"], 2)
        self.assertEqual(stats["coverage"], 100.0)
        self.assertEqual(stats["upstream_commit"], UPSTREAM_SHA)

    def test_raw_scan_counts_are_separate_from_active_unique_keys(self):
        stats = self.module.summarize(*fixture())
        self.assertEqual(stats["scan_raw"], {"added": 5, "changed": 3, "removed": 3})
        self.assertEqual(stats["scan_unique"], {"added": 4, "changed": 3, "removed": 2})
        self.assertEqual(stats["scan_active_unique"], {"added": 2, "changed": 2, "removed": 0})
        self.assertEqual(stats["scan_removed_obsolete_unique"], 1)
        self.assertEqual(stats["newly_effective"], 3)

    def test_missing_is_not_newly_effective(self):
        catalog, zh, retained, pending = fixture()
        del zh["entries"]["new"]
        stats = self.module.summarize(catalog, zh, retained, pending)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["effective"], 2)
        self.assertEqual(stats["changed_display_translations"], 1)
        self.assertEqual(stats["newly_effective"], 2)
        self.assertAlmostEqual(stats["coverage"], 200 / 3)

    def test_empty_translation_is_missing(self):
        catalog, zh, retained, pending = fixture()
        zh["entries"]["new"]["text"] = ""
        stats = self.module.summarize(catalog, zh, retained, pending)
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["newly_effective"], 2)

    def test_stale_translation_is_not_effective(self):
        catalog, zh, retained, pending = fixture()
        zh["entries"]["new"]["source_hash"] = digest("Older Apply")
        stats = self.module.summarize(catalog, zh, retained, pending)
        self.assertEqual(stats["stale"], 1)
        self.assertEqual(stats["effective"], 2)
        self.assertEqual(stats["machine_translated"], 1)
        self.assertEqual(stats["newly_effective"], 2)

    def test_preserves_input_and_ai_review_does_not_upgrade_state(self):
        values = fixture()
        original = deepcopy(values)
        stats = self.module.summarize(*values)
        self.assertEqual(values, original)
        self.assertEqual(stats["reviewed"], 1)
        self.assertEqual(stats["machine_translated"], 2)

    def test_catalog_hash_must_match_actual_source(self):
        catalog, zh, retained, pending = fixture()
        catalog["entries"]["new"]["source_hash"] = digest("wrong")
        with self.assertRaisesRegex(ValueError, "source_hash"):
            self.module.summarize(catalog, zh, retained, pending)

    def test_malformed_translation_hash_is_rejected(self):
        for bad in (None, "", "wrong", "f" * 63, "g" * 64):
            with self.subTest(bad=bad):
                catalog, zh, retained, pending = fixture()
                zh["entries"]["new"]["source_hash"] = bad
                with self.assertRaisesRegex(ValueError, "source_hash"):
                    self.module.summarize(catalog, zh, retained, pending)

    def test_unknown_state_is_rejected_even_for_empty_or_stale_entry(self):
        for text, source_hash in (("应用", digest("Apply")), ("", digest("Apply")),
                                  ("应用", digest("Older Apply"))):
            with self.subTest(text=text, source_hash=source_hash):
                catalog, zh, retained, pending = fixture()
                zh["entries"]["new"].update(text=text, source_hash=source_hash, state="ai_reviewed")
                with self.assertRaisesRegex(ValueError, "state"):
                    self.module.summarize(catalog, zh, retained, pending)

    def test_retained_entries_must_match_source_and_unchanged_translation(self):
        changes = [
            lambda r, z: r["entries"][0].update(source="CPU"),
            lambda r, z: r["entries"][0].update(reason=""),
            lambda r, z: r["entries"][0].update(key="gone"),
            lambda r, z: r["entries"].append(deepcopy(r["entries"][0])),
            lambda r, z: z["entries"]["tech"].update(text="显卡"),
            lambda r, z: z["entries"]["tech"].update(source_hash=digest("CPU")),
            lambda r, z: z["entries"].pop("tech"),
        ]
        for change in changes:
            with self.subTest(change=change):
                catalog, zh, retained, pending = fixture()
                change(retained, zh)
                with self.assertRaisesRegex(ValueError, "retained"):
                    self.module.summarize(catalog, zh, retained, pending)

    def test_undeclared_unchanged_translation_is_rejected(self):
        catalog, zh, retained, pending = fixture()
        retained["entries"] = []
        with self.assertRaisesRegex(ValueError, "retained"):
            self.module.summarize(catalog, zh, retained, pending)

    def test_retained_upstream_commit_must_match_catalog(self):
        catalog, zh, retained, pending = fixture()
        retained["upstream_commit"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "upstream_commit"):
            self.module.summarize(catalog, zh, retained, pending)

    def test_missing_scan_arrays_and_non_string_keys_are_rejected(self):
        for scan in ({}, {"added": "new", "changed": [], "removed": []},
                     {"added": [{}], "changed": [], "removed": []}):
            with self.subTest(scan=scan):
                catalog, zh, retained, pending = fixture()
                pending["scan"] = scan
                with self.assertRaisesRegex(ValueError, "scan"):
                    self.module.summarize(catalog, zh, retained, pending)

    def test_empty_active_catalog_has_no_false_complete_percentage(self):
        catalog, zh, retained, pending = fixture()
        catalog["entries"] = {}
        retained["entries"] = []
        stats = self.module.summarize(catalog, zh, retained, pending)
        self.assertEqual(stats["total"], 0)
        self.assertIsNone(stats["coverage"])
        self.assertEqual(stats["effective"], 0)

    def test_published_release_numbers_are_computed_from_its_commit(self):
        available = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", PUBLISHED_CN_SHA + "^{commit}"],
            capture_output=True)
        if available.returncode:
            self.skipTest("Historical release commit is absent in this shallow checkout")

        def read(path):
            result = subprocess.run(
                ["git", "-C", str(ROOT), "show", PUBLISHED_CN_SHA + ":" + path],
                check=True, capture_output=True)
            return json.loads(result.stdout.decode("utf-8-sig"))

        stats = self.module.summarize(
            read("Localization/master/catalog.json"), read("Localization/zh-CN.json"),
            read("Localization/retained-English.json"), read("Localization/master/pending.json"))
        expected = {"total": 2385, "effective": 2385, "changed_display_translations": 2191,
                    "retained_technical_entries": 194, "missing": 0, "stale": 0,
                    "reviewed": 244, "machine_translated": 2141}
        for key, value in expected.items():
            self.assertEqual(stats[key], value, key)


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("f5_release_notes")

    def test_rendered_section_is_scoped_and_pins_evidence_to_full_commit(self):
        stats = self.module.summarize(*fixture())
        text = self.module.render_section(stats, CN_SHA)
        self.assertTrue(text.startswith(self.module.BEGIN_MARKER + "\n"))
        self.assertTrue(text.endswith(self.module.END_MARKER))
        for required in ("静态词库覆盖", "GPU", "游戏", "视觉", "machine_translated",
                         "reviewed", "原始", "去重", "人工", "不是所有运行时 UI"):
            self.assertIn(required, text)
        base = "https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN"
        self.assertIn(f"{base}/blob/{CN_SHA}/COVERAGE.md", text)
        self.assertIn(f"{base}/tree/{CN_SHA}/reports", text)
        self.assertIn(f"{base}/commit/{CN_SHA}", text)
        self.assertIn(UPSTREAM_SHA, text)

    def test_render_does_not_claim_complete_when_missing_or_stale(self):
        catalog, zh, retained, pending = fixture()
        del zh["entries"]["new"]
        zh["entries"]["old"]["source_hash"] = digest("Older Quality")
        text = self.module.render_section(
            self.module.summarize(catalog, zh, retained, pending), CN_SHA)
        self.assertIn("33.33%", text)
        self.assertNotIn("100%", text)
        self.assertNotIn("100.00%", text)
        self.assertIn("缺失 1", text)
        self.assertIn("过期 1", text)

    def test_empty_active_catalog_render_uses_no_percentage(self):
        catalog, zh, retained, pending = fixture()
        catalog["entries"] = {}
        retained["entries"] = []
        text = self.module.render_section(
            self.module.summarize(catalog, zh, retained, pending), CN_SHA)
        self.assertIn("无活动条目", text)
        self.assertNotIn("100", text)

    def test_full_cn_commit_is_required(self):
        stats = self.module.summarize(*fixture())
        for bad in ("", "a" * 7, "a" * 39, "a" * 41, "../main", "g" * 40,
                    "a" * 40 + "\n", None):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "commit"):
                    self.module.render_section(stats, bad)


class BodyUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("f5_release_notes")

    def section(self):
        return self.module.render_section(self.module.summarize(*fixture()), CN_SHA)

    def test_insertion_preserves_entire_existing_body_and_ownership_marker(self):
        body = "\ufeffOriginal\r\n<!-- f5-cn-test-release:owned -->\r\n  suffix \t"
        updated = self.module.update_body(body, self.section())
        self.assertTrue(updated.startswith(body))
        self.assertEqual(updated.count("<!-- f5-cn-test-release:owned -->"), 1)
        self.assertEqual(self.module.update_body(updated, self.section()), updated)

    def test_replace_preserves_prefix_and_suffix_exactly_including_crlf(self):
        start, end = self.module.BEGIN_MARKER, self.module.END_MARKER
        prefix = "\ufeff开头\r\n<!-- ownership:keep --> \t\n"
        suffix = "\r\n尾部  \r\n\r\n"
        old = start + "\r\nold progress\r\n" + end
        updated = self.module.update_body(prefix + old + suffix, self.section())
        self.assertEqual(updated, prefix + self.section() + suffix)
        self.assertEqual(self.module.update_body(updated, self.section()), updated)

    def test_empty_body_and_unterminated_original_are_supported(self):
        section = self.section()
        self.assertEqual(self.module.update_body("", section), section)
        self.assertEqual(self.module.update_body("original", section), "original\n\n" + section)

    def test_duplicate_unpaired_or_reversed_markers_are_rejected(self):
        begin, end = self.module.BEGIN_MARKER, self.module.END_MARKER
        for body in (begin, end, end + begin, begin + end + begin + end,
                     begin + begin + end, begin + end + end):
            with self.subTest(body=body):
                with self.assertRaisesRegex(ValueError, "marker"):
                    self.module.update_body(body, self.section())

    def test_section_must_be_exactly_one_marked_block(self):
        begin, end = self.module.BEGIN_MARKER, self.module.END_MARKER
        for section in ("unmarked", begin + "x", "prefix" + self.section(),
                        self.section() + "suffix", begin + begin + end):
            with self.subTest(section=section):
                with self.assertRaisesRegex(ValueError, "section|marker"):
                    self.module.update_body("original", section)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        inputs = ("Localization/master/catalog.json", "Localization/zh-CN.json",
                  "Localization/retained-English.json", "Localization/master/pending.json")
        documents = []
        for path in inputs:
            result = subprocess.run(
                ["git", "-C", str(ROOT), "show", cls.head + ":" + path],
                check=True, capture_output=True)
            documents.append(json.loads(result.stdout.decode("utf-8-sig")))
        cls.committed_stats = importlib.import_module("f5_release_notes").summarize(*documents)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/f5_release_notes.py"), *args],
                              text=True, encoding="utf-8", capture_output=True)

    def test_cli_reads_repository_defaults_and_writes_section(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "section.md"
            result = self.run_cli("--cn-commit", self.head, "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn(f'当前活动条目 {self.committed_stats["total"]}', text)
            self.assertIn(f'已变更中文显示值 {self.committed_stats["changed_display_translations"]}', text)
            self.assertIn(f'有意原样保留技术项 {self.committed_stats["retained_technical_entries"]}', text)

    def test_cli_body_roundtrip_preserves_utf8_bytes_and_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "body.md"
            output = Path(directory) / "updated.md"
            original = b"\xef\xbb\xbfOriginal\r\n<!-- ownership:keep -->\r\n"
            body.write_bytes(original)
            result = self.run_cli("--cn-commit", self.head, "--body-file", str(body),
                                  "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            first = output.read_bytes()
            self.assertTrue(first.startswith(original))
            result = self.run_cli("--cn-commit", self.head, "--body-file", str(output),
                                  "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first, output.read_bytes())

    def test_cli_invalid_input_does_not_touch_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "body.md"
            output.write_bytes(b"keep unchanged")
            result = self.run_cli("--cn-commit", "invalid", "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("commit", result.stderr)
            self.assertEqual(output.read_bytes(), b"keep unchanged")

    def test_cli_uses_labeled_commit_not_later_worktree_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ("Localization/master/catalog.json", "Localization/zh-CN.json",
                     "Localization/retained-English.json", "Localization/master/pending.json")
            for name, data in zip(paths, fixture()):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            commands = [
                ["git", "init", "-q", str(root)],
                ["git", "-C", str(root), "add", "Localization"],
                ["git", "-C", str(root), "-c", "user.name=Offline Test",
                 "-c", "user.email=offline@example.invalid", "commit", "-qm", "Fixture"],
            ]
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True).stdout.strip()
            (root / "Localization/zh-CN.json").write_text('{"entries": {}}')
            output = root / "section.md"
            result = self.run_cli("--cn-commit", commit, "--repo-root", str(root),
                                  "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("当前活动条目 3", output.read_text(encoding="utf-8"))
            self.assertIn("缺失 0", output.read_text(encoding="utf-8"))

    def test_cli_unavailable_commit_does_not_fall_back_to_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "section.md"
            result = self.run_cli("--cn-commit", "f" * 40, "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_cli_git_reads_disable_replacement_objects_and_lazy_network_fetch(self):
        module = importlib.import_module("f5_release_notes")
        results = [subprocess.CompletedProcess(
            ["git"], 0, json.dumps(document).encode(), b"") for document in fixture()]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module.subprocess, "run", side_effect=results) as run:
                result = module.main(["--cn-commit", CN_SHA,
                                      "--output", str(Path(directory) / "section.md")])
            self.assertEqual(result, 0)
            for call in run.call_args_list:
                self.assertIn("--no-replace-objects", call.args[0])
                self.assertIn("--no-lazy-fetch", call.args[0])


if __name__ == "__main__":
    unittest.main()
