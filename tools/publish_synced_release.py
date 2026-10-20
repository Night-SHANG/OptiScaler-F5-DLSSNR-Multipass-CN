#!/usr/bin/env python3
"""Publish one exact-commit, verified continuous-sync F5 test Pre-release.

Only an explicit workflow_dispatch input enables this entry point. Identity is
read from the tracked, compatibility-validated upstream configuration, never
learned from a downloaded package. The original fixed publisher remains fixed.
No credentials are discovered and no tag, release or asset can be replaced.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import f5_release_notes as notes
from f5_upstream_contract import load_contract, validate_config
import publish_test_release as core

ROOT = Path(__file__).resolve().parents[1]


def validate_context(env, event, cfg, contract):
    """Validate authenticated workflow context independently of package metadata."""
    validate_config(cfg, contract)
    required = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': core.REPOSITORY,
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
                'BUILD_RESULT': 'success', 'PORTABLE_RESULT': 'success'}
    for key, value in required.items():
        core.require(env.get(key) == value, f'Sync release gate rejected {key}')
    sha = env.get('GITHUB_SHA', '')
    core.require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{40}', sha), 'Full current CN commit SHA required')
    for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        core.require(re.fullmatch('[1-9][0-9]*', env.get(key, '')), f'Invalid {key}')
    core.require(bool(env.get('GH_TOKEN')), 'Only workflow-provided ephemeral GH_TOKEN authentication is supported')
    core.require(env.get('GITHUB_SERVER_URL', 'https://github.com') == 'https://github.com', 'Unexpected GitHub server')
    core.require(env.get('GH_HOST', 'github.com') == 'github.com', 'Unexpected gh host')
    core.require(isinstance(event, dict) and isinstance(event.get('repository'), dict)
                 and event['repository'].get('full_name') == core.REPOSITORY,
                 'Dispatch event repository mismatch')
    core.require(event.get('ref') in ('main', 'refs/heads/main'), 'Dispatch event ref mismatch')
    inputs = event.get('inputs')
    core.require(isinstance(inputs, dict) and inputs.get('sync_publish') == 'true'
                 and inputs.get('expected_sha') == sha, 'Explicit sync dispatch inputs/current SHA mismatch')
    return {'sha': sha, 'run_id': env['GITHUB_RUN_ID'], 'attempt': env['GITHUB_RUN_ATTEMPT'],
            'event': 'workflow_dispatch', 'upstream': cfg['commit'], 'upstream_version': cfg['upstream_version'],
            'tag': 'cn-test-' + cfg['commit'][:12] + '-' + sha[:12]}


def prepare_publication(artifact_dir, env, event, *, root=ROOT, sync_identity):
    """Pure local preflight; callers must check checkout identity before upload."""
    root, artifact_dir = Path(root), Path(artifact_dir)
    cfg = core.object_json((root / 'upstream.json').read_bytes(), 'upstream.json')
    contract = load_contract(root / 'upstream-contract.json')
    context = validate_context(env, event, cfg, contract)
    core.require(artifact_dir.absolute() == root.absolute() / 'release-artifact',
                 'Only the same-run release-artifact directory is allowed')
    context['sync_identity'] = sync_identity
    core.sync_marker(context)  # Validate the format before any external action.
    loc = root / 'Localization'
    inputs = [loc / 'master/catalog.json', loc / 'zh-CN.json', loc / 'retained-English.json', loc / 'master/pending.json']
    stats = notes.summarize(*(core.object_json(path.read_bytes(), path.name) for path in inputs))
    core.require(stats['upstream_commit'] == cfg['commit'], 'Coverage source does not match current validated upstream')
    core.require(stats['total'] > 0 and stats['missing'] == 0 and stats['stale'] == 0,
                 'Missing, stale or empty localization coverage blocks sync publication')
    context['progress_section'] = notes.render_section(stats, context['sha'])
    package = core.verify_artifact(artifact_dir, context['sha'], loc / 'installers.zh-CN.json',
                                   upstream=cfg['commit'], upstream_version=cfg['upstream_version'])
    return package, context


def verify_checkout(root, expected_sha):
    """Ensure tracked configuration/coverage actually comes from the run commit."""
    core.require(isinstance(expected_sha, str) and re.fullmatch('[0-9a-f]{40}', expected_sha), 'Invalid checkout SHA')
    outputs = []
    for arguments in (('rev-parse', '--verify', 'HEAD'), ('status', '--porcelain', '--untracked-files=no')):
        try:
            result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *arguments],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise core.GateError('Cannot verify current checkout identity') from exc
        core.require(result.returncode == 0, 'Cannot verify current checkout identity')
        outputs.append(result.stdout.decode('utf-8').strip())
    core.require(outputs[0] == expected_sha and not outputs[1], 'Checkout SHA or tracked input cleanliness mismatch')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, default=ROOT / 'release-artifact')
    args = parser.parse_args(argv)
    try:
        event_path = os.environ.get('GITHUB_EVENT_PATH')
        core.require(event_path, 'Missing GitHub workflow_dispatch payload')
        event = core.object_json(Path(event_path).read_bytes(), 'dispatch event')
        verify_checkout(ROOT, os.environ.get('GITHUB_SHA', ''))
        # Loaded only for an explicitly invoked publisher; no module-global mutation.
        from f5_sync import release_identity
        package, context = prepare_publication(args.artifact_dir, os.environ, event, root=ROOT,
                                              sync_identity=release_identity(ROOT))
        print(core.publish(package, context, core.GitHub(release_tag=context['tag'])))
    except (core.GateError, OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f'Sync test release blocked: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
