"""Fixed-release update tests; all GitHub operations use an in-memory transport."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_f5_release_notes import fixture
import f5_release_notes as notes


def stats_fixture():
    catalog, zh, retained, pending = fixture()
    pin = "fadc3bf67f6c8548e94914baec3f2e551ba8d8a4"
    catalog["upstream_commit"] = retained["upstream_commit"] = pin
    return notes.summarize(catalog, zh, retained, pending)


class FakeGitHub:
    def __init__(self, module):
        self.module = module
        self.calls = []
        self.fail_patch = None
        self.after_patch = None
        self.before_second_read = None
        self.release_reads = 0
        self.tag_object = {"type": "commit", "sha": module.CN_COMMIT}
        self.assets = [
            {"id": index, "name": name, "size": 100 + index, "state": "uploaded",
             "digest": "sha256:" + str(index) * 64,
             "url": f"https://api.github.com/repos/{module.REPOSITORY}/releases/assets/{index}",
             "browser_download_url": f"https://github.com/{module.REPOSITORY}/releases/download/{module.TAG}/{name}"}
            for index, name in enumerate(module.ASSET_NAMES, start=1)
        ]
        hashes = {asset["name"]: asset["digest"].split(":")[1] for asset in self.assets}
        manifest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.marker = f"<!-- f5-cn-test-gate:v1 cn_commit={module.CN_COMMIT} assets_sha256={manifest} -->"
        self.release = {
            "id": module.RELEASE_ID, "tag_name": module.TAG, "target_commitish": module.CN_COMMIT,
            "draft": False, "prerelease": True, "name": "Existing release name",
            "html_url": f"https://github.com/{module.REPOSITORY}/releases/tag/{module.TAG}",
            "body": "\ufeffExisting\r\n" + self.marker + "\r\ntrailing  ",
        }

    def api(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        module = self.module
        if method == "GET":
            if path == module.RELEASE_PATH:
                self.release_reads += 1
                if self.release_reads == 2 and self.before_second_read:
                    self.before_second_read(self)
                return deepcopy(self.release)
            if path == module.ASSETS_PATH:
                return deepcopy(self.assets)
            if path == module.TAG_PATH:
                return {"ref": "refs/tags/" + module.TAG, "object": deepcopy(self.tag_object)}
            if path == module.API_ROOT + "git/tags/" + "d" * 40:
                return {"object": {"type": "commit", "sha": module.CN_COMMIT}}
            raise AssertionError(path)
        if method == "PATCH":
            if self.fail_patch == "before":
                raise module.GitHubError("uncertain")
            self.release.update(payload)
            if self.after_patch:
                self.after_patch(self)
            if self.fail_patch == "after":
                raise module.GitHubError("uncertain")
            return deepcopy(self.release)
        raise AssertionError((method, path))

    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("update_release_progress")

    def test_only_body_is_patched_and_existing_content_assets_tag_are_preserved(self):
        github = FakeGitHub(self.module)
        body, assets, tag = github.release["body"], deepcopy(github.assets), deepcopy(github.tag_object)
        result = self.module.update_progress(github, stats_fixture())
        writes = github.writes()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][:2], ("PATCH", self.module.RELEASE_PATH))
        self.assertEqual(set(writes[0][2]), {"body"})
        self.assertTrue(github.release["body"].startswith(body))
        self.assertIn(github.marker, github.release["body"])
        self.assertIn(self.module.CN_COMMIT + "/COVERAGE.md", github.release["body"])
        self.assertEqual(github.assets, assets)
        self.assertEqual(github.tag_object, tag)
        self.assertTrue(result["changed"])
        self.assertEqual(result["release_id"], self.module.RELEASE_ID)

    def test_identical_body_is_not_written(self):
        github = FakeGitHub(self.module)
        stats = stats_fixture()
        github.release["body"] = notes.update_body(
            github.release["body"], notes.render_section(stats, self.module.CN_COMMIT))
        result = self.module.update_progress(github, stats)
        self.assertFalse(result["changed"])
        self.assertEqual(github.writes(), [])

    def test_wrong_release_headers_fail_before_any_mutation(self):
        for field, value in (("id", 1), ("tag_name", "other"), ("target_commitish", "main"),
                             ("target_commitish", "f" * 40), ("draft", True), ("prerelease", False)):
            with self.subTest(field=field, value=value):
                github = FakeGitHub(self.module)
                github.release[field] = value
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats_fixture())
                self.assertEqual(github.writes(), [])

    def test_wrong_tag_commit_and_malformed_tag_are_rejected(self):
        for obj in ({"type": "commit", "sha": "f" * 40}, {"type": "tree", "sha": "f" * 40},
                    {"type": "commit", "sha": "short"}):
            with self.subTest(obj=obj):
                github = FakeGitHub(self.module)
                github.tag_object = obj
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats_fixture())
                self.assertEqual(github.writes(), [])

    def test_annotated_tag_is_resolved_without_changing_it(self):
        github = FakeGitHub(self.module)
        github.tag_object = {"type": "tag", "sha": "d" * 40}
        self.module.update_progress(github, stats_fixture())
        self.assertEqual(github.tag_object, {"type": "tag", "sha": "d" * 40})
        self.assertEqual(len(github.writes()), 1)

    def test_missing_duplicate_or_wrong_ownership_marker_is_rejected(self):
        for change in (lambda body, marker: body.replace(marker, ""),
                       lambda body, marker: body + marker,
                       lambda body, marker: body.replace("assets_sha256=", "assets_sha256=0"),
                       lambda body, marker: body.replace(self.module.CN_COMMIT, "e" * 40)):
            with self.subTest(change=change):
                github = FakeGitHub(self.module)
                github.release["body"] = change(github.release["body"], github.marker)
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats_fixture())
                self.assertEqual(github.writes(), [])

    def test_duplicate_progress_markers_are_rejected_before_write(self):
        github = FakeGitHub(self.module)
        section = notes.render_section(stats_fixture(), self.module.CN_COMMIT)
        github.release["body"] += section + section
        with self.assertRaisesRegex(ValueError, "marker"):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(github.writes(), [])

    def test_ownership_inside_replaced_section_is_rejected_before_write(self):
        github = FakeGitHub(self.module)
        github.release["body"] = notes.BEGIN_MARKER + "\n" + github.marker + "\n" + notes.END_MARKER
        with self.assertRaisesRegex(self.module.GateError, "ownership"):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(github.writes(), [])

    def test_incomplete_coverage_is_blocked(self):
        for field in ("missing", "stale"):
            with self.subTest(field=field):
                github = FakeGitHub(self.module)
                stats = stats_fixture()
                stats[field] = 1
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats)
                self.assertEqual(github.writes(), [])

    def test_noncanonical_upstream_is_blocked(self):
        github = FakeGitHub(self.module)
        stats = stats_fixture()
        stats["upstream_commit"] = "e" * 40
        with self.assertRaises(self.module.GateError):
            self.module.update_progress(github, stats)
        self.assertEqual(github.writes(), [])

    def test_missing_extra_duplicate_and_unuploaded_assets_are_rejected(self):
        mutations = [
            lambda g: g.assets.pop(),
            lambda g: g.assets.append(deepcopy(g.assets[0])),
            lambda g: g.assets[0].update(name="unexpected.zip"),
            lambda g: g.assets[0].update(state="new"),
            lambda g: g.assets[0].update(digest=None),
            lambda g: g.assets[0].update(size=0),
            lambda g: g.assets[0].update(id=0),
            lambda g: g.assets[0].update(browser_download_url="https://example.org/file.zip"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                github = FakeGitHub(self.module)
                mutate(github)
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats_fixture())
                self.assertEqual(github.writes(), [])

    def test_concurrent_body_change_before_patch_is_rejected(self):
        github = FakeGitHub(self.module)
        github.before_second_read = lambda g: g.release.update(body=g.release["body"] + "\nExternal edit")
        with self.assertRaisesRegex(self.module.GateError, "changed"):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(github.writes(), [])

    def test_uncertain_success_is_read_back_without_retry(self):
        github = FakeGitHub(self.module)
        github.fail_patch = "after"
        result = self.module.update_progress(github, stats_fixture())
        self.assertTrue(result["changed"])
        self.assertTrue(result["reconciled"])
        self.assertEqual(len(github.writes()), 1)
        self.assertEqual(github.calls[-1][0], "GET")

    def test_uncertain_failure_reads_back_and_does_not_retry(self):
        github = FakeGitHub(self.module)
        github.fail_patch = "before"
        with self.assertRaisesRegex(self.module.GateError, "body|outcome"):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(len(github.writes()), 1)
        self.assertEqual(github.calls[-1][0], "GET")

    def test_every_asset_identity_field_is_checked_after_patch(self):
        values = {"id": 900, "name": "wrong.zip", "size": 999, "digest": "sha256:" + "e" * 64,
                  "url": "https://api.github.com/changed", "browser_download_url": "https://example.org/x"}
        for field, value in values.items():
            with self.subTest(field=field):
                github = FakeGitHub(self.module)
                github.after_patch = lambda g: g.assets[0].update({field: value})
                with self.assertRaises(self.module.GateError):
                    self.module.update_progress(github, stats_fixture())
                self.assertEqual(len(github.writes()), 1)

    def test_tag_identity_change_with_same_peeled_commit_is_rejected(self):
        github = FakeGitHub(self.module)
        github.after_patch = lambda g: setattr(g, "tag_object", {"type": "tag", "sha": "d" * 40})
        with self.assertRaises(self.module.GateError):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(len(github.writes()), 1)

    def test_body_readback_must_equal_expected_bytes(self):
        github = FakeGitHub(self.module)
        github.after_patch = lambda g: g.release.update(body=g.release["body"].replace("\r\n", "\n"))
        with self.assertRaisesRegex(self.module.GateError, "body"):
            self.module.update_progress(github, stats_fixture())
        self.assertEqual(len(github.writes()), 1)


class InputAndTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("update_release_progress")

    def test_inputs_are_read_with_git_show_at_exact_release_commit(self):
        values = list(fixture())
        values[0]["upstream_commit"] = values[2]["upstream_commit"] = self.module.UPSTREAM_COMMIT
        by_path = dict(zip(self.module.INPUT_PATHS, values))
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            object_name = command[-1]
            commit, path = object_name.split(":", 1)
            self.assertEqual(commit, self.module.CN_COMMIT)
            return subprocess.CompletedProcess(command, 0, json.dumps(by_path[path]).encode(), b"")

        with patch.object(self.module.subprocess, "run", side_effect=fake_run):
            stats = self.module.load_release_stats(ROOT)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(call[:6] == [
            "git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(ROOT), "show"] for call in calls))

    def test_git_failure_never_falls_back_to_worktree(self):
        with patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["git"], 128, b"", b"missing commit")):
            with self.assertRaises(self.module.GateError):
                self.module.load_release_stats(ROOT)

    def test_actions_context_is_narrow_without_reading_token_value(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": self.module.REPOSITORY,
               "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push",
               "GH_TOKEN": "never-read", "GITHUB_SERVER_URL": "https://github.com"}

        class NoTokenRead(dict):
            def get(self, key, default=None):
                if key == "GH_TOKEN":
                    raise AssertionError("must not read token")
                return super().get(key, default)
            def __getitem__(self, key):
                if key == "GH_TOKEN":
                    raise AssertionError("must not read token")
                return super().__getitem__(key)

        self.module.validate_context(NoTokenRead(env))
        self.module.validate_context(NoTokenRead({**env, "GITHUB_EVENT_NAME": "workflow_dispatch"}))
        for key, value in (("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "other/repo"),
                           ("GITHUB_REF", "refs/heads/other"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GH_HOST", "evil.invalid")):
            with self.subTest(key=key):
                with self.assertRaises(self.module.GateError):
                    self.module.validate_context(NoTokenRead({**env, key: value}))

    def test_transport_rejects_every_mutation_except_fixed_body_patch(self):
        client = self.module.GitHub()
        with patch.object(self.module.subprocess, "run") as run:
            for method, path, payload in [
                ("POST", self.module.API_ROOT + "releases", {"body": "x"}),
                ("DELETE", self.module.RELEASE_PATH, None),
                ("PATCH", self.module.RELEASE_PATH, {"body": "x", "draft": False}),
                ("PATCH", self.module.API_ROOT + "releases/1", {"body": "x"}),
                ("GET", "repos/other/repo/releases/1", None),
            ]:
                with self.subTest(method=method, path=path):
                    with self.assertRaises(self.module.GateError):
                        client.api(method, path, payload)
            run.assert_not_called()

    def test_transport_sends_only_body_json_to_fixed_host(self):
        client = self.module.GitHub()
        with patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["gh"], 0, b'{"id":418050844}', b"")) as run:
            client.api("PATCH", self.module.RELEASE_PATH, {"body": "中文\r\n"})
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["gh", "api", "--hostname", "github.com", "--method", "PATCH"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"body": "中文\r\n"})

    def test_transport_does_not_echo_error_output(self):
        with patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["gh"], 1, b"private output", b"secret error")):
            with self.assertRaises(self.module.GitHubError) as caught:
                self.module.GitHub().api("GET", self.module.RELEASE_PATH)
        self.assertNotIn("private", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_workflow_has_narrow_triggers_permissions_and_ephemeral_token(self):
        workflow = (ROOT / ".github/workflows/update-release-notes.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("pull_request", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("GH_TOKEN: ${{ github.token }}", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("github.repository == '" + self.module.REPOSITORY + "'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("group: f5-cn-test-release-v0.1.32-cn-test.1", workflow)
        self.assertIn("python tools/update_release_progress.py --receipt", workflow)


if __name__ == "__main__":
    unittest.main()
