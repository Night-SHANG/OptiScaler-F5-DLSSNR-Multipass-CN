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

from f5_upstream_contract import load_contract, validate_config as validate_upstream_config, verify_source

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git"
MARKER = ".f5-cn-managed.json"


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def validate_config(cfg: dict, contract: dict | None = None) -> None:
    validate_upstream_config(cfg, contract if contract is not None else load_contract(ROOT / "upstream-contract.json"))


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
    old_pin = owner.get("commit") if isinstance(owner, dict) else None
    expected = {"schema": 1, "root": str(root.resolve()), "repository": REPOSITORY, "commit": old_pin}
    if (owner != expected or type(owner.get("schema")) is not int
            or not isinstance(old_pin, str) or not re.fullmatch(r"[0-9a-f]{40}", old_pin)
            or not (path / ".git").is_dir() or (path / ".git").is_symlink()):
        raise ValueError("Managed-tree ownership does not match; refusing to remove it")
    if Path(run("git", "rev-parse", "--show-toplevel", cwd=path)).resolve() != path:
        raise ValueError("Refusing to remove a linked or parent Git worktree")
    if run("git", "remote", "get-url", "origin", cwd=path) != REPOSITORY:
        raise ValueError("Managed-tree origin changed; refusing to remove it")
    # Configuration may advance, but this marker must still identify the exact
    # earlier checkout this tool created. Never infer ownership from origin alone.
    if run("git", "rev-parse", "HEAD", cwd=path) != old_pin:
        raise ValueError("Managed-tree recorded commit changed; refusing to remove it")

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


def verify_checkout(path: Path, cfg: dict, contract: dict) -> str:
    verify_source(path, cfg, contract)
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
    contract = load_contract(ROOT / "upstream-contract.json")
    validate_config(cfg, contract)
    pin, version = cfg["commit"], cfg["upstream_version"]
    path = bounded_worktree(ROOT, args.worktree)
    if args.verify:
        if args.clean:
            raise ValueError("--verify cannot be combined with --clean")
        status = verify_checkout(path, cfg, contract)
    else:
        if path.exists():
            if not args.clean:
                raise ValueError("_upstream exists; use --clean only for this tool's owned scratch tree")
            clean_owned_worktree(ROOT, path)
        # text=auto still honors core.eol when autocrlf=false; pin LF on Windows too.
        run("git", "clone", "--no-checkout", "--no-tags", "--depth=1", "-c", "core.autocrlf=false", "-c", "core.eol=lf", REPOSITORY, str(path))
        (path / MARKER).write_text(json.dumps({"schema": 1, "root": str(ROOT.resolve()),
            "repository": REPOSITORY, "commit": pin}, indent=2) + "\n", encoding="utf-8")
        run("git", "fetch", "--no-tags", "--depth=1", "origin", pin, cwd=path)
        run("git", "checkout", "--detach", pin, cwd=path)
        # Validate actual checkout bytes and frozen dependency metadata before
        # following any submodule URL or executing any upstream tool.
        verify_source(path, cfg, contract)
        # Never use --remote: the superproject and each nested tree own the gitlink pins.
        run("git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "submodule", "update", "--init", "--recursive", cwd=path)
        status = verify_checkout(path, cfg, contract)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "upstream-materialization.json").write_text(json.dumps({
        "repository": REPOSITORY, "upstream_commit": pin, "upstream_version": version,
        "recursive_submodules": status.splitlines(), "verified_pristine": True,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {version} at {pin}, including all recursive gitlinks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.output:
            print(error.output, file=sys.stderr)
        raise SystemExit(1)
