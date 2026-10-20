#!/usr/bin/env python3
"""Materialize one pinned upstream in an explicitly owned, bounded scratch tree."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PIN = "fadc3bf67f6c8548e94914baec3f2e551ba8d8a4"
REPOSITORY = "https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git"
VERSION = "v0.1.32"
MARKER = ".f5-cn-managed.json"


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def validate_config(cfg: dict) -> None:
    if cfg.get("commit") != PIN or not re.fullmatch(r"[0-9a-f]{40}", cfg["commit"]):
        raise ValueError("upstream.json must name the audited full F5 commit; floating refs are forbidden")
    if cfg.get("repository") != REPOSITORY or cfg.get("upstream_version") != VERSION:
        raise ValueError("Upstream repository/version does not match the audited F5 pin")


def bounded_worktree(root: Path, path: Path) -> Path:
    root = root.resolve()
    candidate = Path(os.path.abspath(path))
    expected = root / "_upstream"
    # Lexical AND resolved identity: reject '..' aliases, symlinks and Windows junctions.
    if candidate != expected or candidate.is_symlink() or candidate.resolve() != expected:
        raise ValueError("Only the real repository-local _upstream directory is allowed")
    if candidate.exists() and getattr(candidate, "is_junction", lambda: False)():
        raise ValueError("A junction cannot be a managed upstream tree")
    return candidate


def clean_owned_worktree(root: Path, path: Path) -> None:
    path = bounded_worktree(root, path)
    marker = path / MARKER
    if not marker.is_file() or marker.is_symlink():
        raise ValueError("Existing _upstream is not owned by this tool; refusing to remove it")
    owner = json.loads(marker.read_text(encoding="utf-8"))
    expected = {"schema": 1, "root": str(root.resolve()), "repository": REPOSITORY, "commit": PIN}
    if owner != expected or not (path / ".git").is_dir() or (path / ".git").is_symlink():
        raise ValueError("Managed-tree ownership does not match; refusing to remove it")
    if Path(run("git", "rev-parse", "--show-toplevel", cwd=path)).resolve() != path:
        raise ValueError("Refusing to remove a linked or parent Git worktree")
    if run("git", "remote", "get-url", "origin", cwd=path) != REPOSITORY:
        raise ValueError("Managed-tree origin changed; refusing to remove it")

    def readonly_retry(func, name, exc):
        # Git pack files are read-only on Windows. Never follow a link in the retry.
        if Path(name).is_symlink():
            raise exc[1]
        os.chmod(name, stat.S_IWRITE | stat.S_IREAD)
        func(name)

    shutil.rmtree(path, onerror=readonly_retry)


def validate_submodule_status(status: str) -> None:
    lines = status.splitlines()
    if not lines or any(not re.match(r"^ [0-9a-f]{40} \S+", line) for line in lines):
        raise ValueError("Every recursive submodule must be initialized at its exact pinned gitlink")


def verify_checkout(path: Path) -> str:
    if run("git", "rev-parse", "HEAD", cwd=path) != PIN:
        raise ValueError("Materialized upstream HEAD does not match the fixed pin")
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=path):
        raise ValueError("Pinned upstream or a submodule has tracked modifications")
    # check_output .strip() would discard the leading clean-status space.
    status = subprocess.check_output(["git", "submodule", "status", "--recursive"], cwd=path, text=True)
    validate_submodule_status(status)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, default=ROOT / "_upstream")
    parser.add_argument("--clean", action="store_true", help="replace ONLY this tool's owned _upstream scratch tree")
    parser.add_argument("--verify", action="store_true", help="verify a pristine materialized checkout without network access")
    args = parser.parse_args()
    cfg = json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))
    validate_config(cfg)
    path = bounded_worktree(ROOT, args.worktree)
    if args.verify:
        if args.clean:
            raise ValueError("--verify cannot be combined with --clean")
        status = verify_checkout(path)
    else:
        if path.exists():
            if not args.clean:
                raise ValueError("_upstream exists; use --clean only for this tool's owned scratch tree")
            clean_owned_worktree(ROOT, path)
        # text=auto still honors core.eol when autocrlf=false; pin LF on Windows too.
        run("git", "clone", "--no-checkout", "--no-tags", "--depth=1", "-c", "core.autocrlf=false", "-c", "core.eol=lf", REPOSITORY, str(path))
        (path / MARKER).write_text(json.dumps({"schema": 1, "root": str(ROOT.resolve()),
            "repository": REPOSITORY, "commit": PIN}, indent=2) + "\n", encoding="utf-8")
        run("git", "fetch", "--no-tags", "--depth=1", "origin", PIN, cwd=path)
        run("git", "checkout", "--detach", PIN, cwd=path)
        # Never use --remote: the superproject and each nested tree own the gitlink pins.
        run("git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "submodule", "update", "--init", "--recursive", cwd=path)
        status = verify_checkout(path)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "upstream-materialization.json").write_text(json.dumps({
        "repository": REPOSITORY, "upstream_commit": PIN, "upstream_version": VERSION,
        "recursive_submodules": status.splitlines(), "verified_pristine": True,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {VERSION} at {PIN}, including all recursive gitlinks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.output:
            print(error.output, file=sys.stderr)
        raise SystemExit(1)
