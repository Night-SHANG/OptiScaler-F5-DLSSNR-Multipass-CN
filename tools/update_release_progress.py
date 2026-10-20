#!/usr/bin/env python3
"""Update only the progress section of one already-published F5 test release.

The workflow supplies ephemeral authentication to gh. This script never reads
token contents, discovers credentials, creates releases, or changes tags/assets.
Every uncertain PATCH is followed by readback; it is never retried automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from f5_release_notes import REPOSITORY, render_section, summarize, update_body

ROOT = Path(__file__).resolve().parents[1]
TAG = "v0.1.32-cn-test.1"
RELEASE_ID = 418050844
CN_COMMIT = "6c9128d67a8fb5a21303fabb8affd032806ab862"
UPSTREAM_COMMIT = "fadc3bf67f6c8548e94914baec3f2e551ba8d8a4"
API_ROOT = f"repos/{REPOSITORY}/"
RELEASE_PATH = API_ROOT + f"releases/{RELEASE_ID}"
ASSETS_PATH = RELEASE_PATH + "/assets?per_page=100&page=1"
TAG_PATH = API_ROOT + "git/ref/tags/" + TAG
PACKAGE = f"OptiScaler-F5-DLSSNR-Multipass-CN-v0.1.32-cn-{CN_COMMIT[:12]}-{UPSTREAM_COMMIT[:12]}.zip"
ASSET_NAMES = (PACKAGE, PACKAGE + ".sha256", "build-metadata.json")
INPUT_PATHS = (
    "Localization/master/catalog.json", "Localization/zh-CN.json",
    "Localization/retained-English.json", "Localization/master/pending.json",
)
ASSET_FIELDS = ("name", "id", "digest", "size", "url", "browser_download_url", "state")
RELEASE_FIELDS = ("id", "tag_name", "target_commitish", "draft", "prerelease", "name", "html_url")


class GateError(RuntimeError):
    """The fixed target or required proof is inconsistent."""


class GitHubError(GateError):
    """The API operation failed or its outcome is uncertain."""


def require(condition, message):
    if not condition:
        raise GateError(message)


def validate_context(env):
    required = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_REF": "refs/heads/main"}
    for key, value in required.items():
        require(env.get(key) == value, f"Progress gate rejected {key}")
    require(env.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch"), "Unsupported workflow event")
    require(env.get("GITHUB_SERVER_URL", "https://github.com") == "https://github.com",
            "Unexpected GitHub server")
    require(env.get("GH_HOST", "github.com") == "github.com", "Unexpected gh host")
    # Check the workflow contract, without retrieving or printing the secret.
    require("GH_TOKEN" in env, "Workflow-provided GH_TOKEN is required")


def _json(data, name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key in {name}")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise GateError(f"Invalid JSON in {name}") from exc


def load_release_stats(repo_root=ROOT):
    """Use committed release inputs only; never fall back to a newer worktree."""
    documents = []
    for path in INPUT_PATHS:
        try:
            result = subprocess.run(
                ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(repo_root),
                 "show", f"{CN_COMMIT}:{path}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GateError("Cannot read pinned release inputs") from exc
        require(result.returncode == 0, f"Pinned release input unavailable: {path}")
        documents.append(_json(result.stdout, path))
    return summarize(*documents)


class GitHub:
    """Fixed-host, fixed-endpoint transport; the sole mutation is a body PATCH."""
    def api(self, method, path, payload=None):
        if method == "GET":
            require(path in (RELEASE_PATH, ASSETS_PATH, TAG_PATH) or
                    re.fullmatch(re.escape(API_ROOT) + r"git/tags/[0-9a-f]{40}", path),
                    "Read destination outside the fixed release/tag")
            require(payload is None, "GET payload is forbidden")
        elif method == "PATCH":
            require(path == RELEASE_PATH and isinstance(payload, dict)
                    and set(payload) == {"body"} and isinstance(payload["body"], str),
                    "Only the fixed release body may be patched")
        else:
            raise GateError("Only read and fixed-body PATCH operations are supported")
        command = ["gh", "api", "--hostname", "github.com", "--method", method,
                   "-H", "Accept: application/vnd.github+json",
                   "-H", "X-GitHub-Api-Version: 2022-11-28", path]
        encoded = None
        if payload is not None:
            command += ["--input", "-"]
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            result = subprocess.run(command, input=encoded, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=False, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError("GitHub outcome uncertain; read back before any retry") from exc
        if result.returncode:
            raise GitHubError("GitHub operation failed; no automatic mutation retry")
        try:
            return _json(result.stdout, "GitHub response")
        except GateError as exc:
            raise GitHubError("GitHub response invalid; operation outcome uncertain") from exc


def _tag(github):
    ref = github.api("GET", TAG_PATH)
    require(isinstance(ref, dict) and ref.get("ref") == "refs/tags/" + TAG, "Wrong release tag")
    obj = ref.get("object")
    identity = []
    for _ in range(6):
        require(isinstance(obj, dict), "Malformed tag object")
        kind, sha = obj.get("type"), obj.get("sha")
        require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha), "Invalid tag SHA")
        identity.append({"type": kind, "sha": sha})
        if kind == "commit":
            require(sha == CN_COMMIT, "Tag points to a different commit")
            return identity
        require(kind == "tag", "Tag does not resolve to a commit")
        annotated = github.api("GET", API_ROOT + "git/tags/" + sha)
        require(isinstance(annotated, dict), "Malformed annotated tag")
        obj = annotated.get("object")
    raise GateError("Excessive annotated-tag nesting")


def _snapshot(github):
    release = github.api("GET", RELEASE_PATH)
    require(isinstance(release, dict), "Malformed release response")
    require(type(release.get("id")) is int and release["id"] == RELEASE_ID
            and release.get("tag_name") == TAG and release.get("target_commitish") == CN_COMMIT
            and release.get("draft") is False and release.get("prerelease") is True,
            "Release target/type mismatch")
    require(release.get("html_url") == f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
            "Unexpected release URL")
    body = release.get("body")
    require(isinstance(body, str), "Release body must be a string")
    tag = _tag(github)
    assets = github.api("GET", ASSETS_PATH)
    require(isinstance(assets, list) and len(assets) == 3, "Expected exactly three release assets")
    names, ids, identities, hashes = set(), set(), [], {}
    for asset in assets:
        require(isinstance(asset, dict), "Malformed release asset")
        name, asset_id, digest = asset.get("name"), asset.get("id"), asset.get("digest")
        require(name in ASSET_NAMES and name not in names, "Unexpected or duplicate asset name")
        require(type(asset_id) is int and asset_id > 0 and asset_id not in ids, "Invalid or duplicate asset ID")
        require(type(asset.get("size")) is int and asset["size"] > 0 and asset.get("state") == "uploaded",
                "Asset is empty or not uploaded")
        require(isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
                "Asset SHA-256 digest is missing or invalid")
        require(asset.get("url") == f"https://api.github.com/repos/{REPOSITORY}/releases/assets/{asset_id}"
                and asset.get("browser_download_url") ==
                f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{name}",
                "Asset URL is inconsistent")
        names.add(name)
        ids.add(asset_id)
        hashes[name] = digest.removeprefix("sha256:")
        identities.append({key: asset.get(key) for key in ASSET_FIELDS})
    manifest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    marker = f"<!-- f5-cn-test-gate:v1 cn_commit={CN_COMMIT} assets_sha256={manifest} -->"
    require(body.count("<!-- f5-cn-test-gate:") == 1 and body.count(marker) == 1,
            "Release ownership marker or asset manifest mismatch")
    return {
        "header": {key: release.get(key) for key in RELEASE_FIELDS}, "body": body,
        "tag": tag, "assets": sorted(identities, key=lambda item: item["name"]), "ownership": marker,
    }


def update_progress(github, stats):
    """Validate, update once if needed, and read back unchanged release identities."""
    require(stats.get("upstream_commit") == UPSTREAM_COMMIT, "Unexpected upstream catalog commit")
    require(stats.get("total", 0) > 0 and stats.get("missing") == 0 and stats.get("stale") == 0,
            "Incomplete static catalog coverage blocks the release body update")
    before = _snapshot(github)
    expected_body = update_body(before["body"], render_section(stats, CN_COMMIT))
    require(expected_body.count(before["ownership"]) == 1,
            "Progress section overlaps the release ownership marker")
    # Catch outside edits observed while calculating the replacement. GitHub has
    # no documented compare-and-swap body update; an external edit in the final
    # request window cannot be excluded. A post-write mismatch stops, not rewrites.
    current = _snapshot(github)
    require(current == before, "Release body, assets, or tag changed before PATCH")
    changed = expected_body != before["body"]
    reconciled = False
    if changed:
        try:
            github.api("PATCH", RELEASE_PATH, {"body": expected_body})
        except GitHubError:
            reconciled = True
        after = _snapshot(github)
        require(after["body"] == expected_body, "Release body update outcome not verified; no retry performed")
        for field in ("header", "tag", "assets", "ownership"):
            require(after[field] == before[field], f"Release {field} changed during body update")
    else:
        after = current
    return {
        "release_id": RELEASE_ID, "tag": TAG, "cn_commit": CN_COMMIT,
        "release_url": before["header"]["html_url"], "changed": changed, "reconciled": reconciled,
        "body_sha256_before": hashlib.sha256(before["body"].encode("utf-8")).hexdigest(),
        "body_sha256_after": hashlib.sha256(after["body"].encode("utf-8")).hexdigest(),
        "assets_unchanged": True, "tag_unchanged": True,
        "assets": after["assets"], "tag_identity": after["tag"], "stats": stats,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, help="Write the verified readback receipt locally")
    args = parser.parse_args(argv)
    try:
        validate_context(os.environ)
        receipt = update_progress(GitHub(), load_release_stats(ROOT))
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Release progress verified: " + receipt["release_url"]
              + (" (updated)" if receipt["changed"] else " (already current)"))
    except (GateError, OSError, ValueError) as exc:
        print(f"Release progress blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
