#!/usr/bin/env python3
"""Fail-closed, credential-free-translation F5 upstream synchronization.

GitHub's job-scoped token is used only for this repository's bounded data commit
and an exact-SHA build dispatch. No translation service or saved credential is
configured here. New wording without approved translation memory stops the job.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPO = 'Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN'
UPSTREAM = 'janblade/OptiScaler-F5-DLSSNR-Multipass'
URL = 'https://github.com/' + UPSTREAM + '.git'
SHA = re.compile(r'[0-9a-f]{40}')
VERSION = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')
DATA_PATHS = frozenset({
    'upstream.json', 'Localization/master/catalog.json', 'Localization/master/en-US.json',
    'Localization/master/pending.json', 'Localization/master/meta.json',
    'Localization/catalog.json', 'Localization/en-US.json', 'Localization/pending.json',
    'Localization/zh-CN.json', 'Localization/retained-English.json',
    'Localization/installers.zh-CN.json', 'reports/coverage-inventory.json',
})
# Output-affecting content, excluding maintenance/workflow/report bookkeeping.
IDENTITY_PATHS = (
    'Localization/master/catalog.json', 'Localization/zh-CN.json',
    'Localization/composed-templates.json', 'Localization/installers.zh-CN.json',
    'Localization/OptiScalerCN.ini', 'tools/localize_f5.py', 'tools/localize_source.py',
    'tools/generate_cpp.py', 'tools/f5_font_patch.py', 'tools/f5_boundaries.json',
    'tools/f5_installer_patch.py', 'tools/loclib.py', 'tools/package.ps1',
    'README.zh-CN.md', 'UPSTREAM.md',
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def resolve_candidate(cfg: dict, head: str, latest_tag: str, latest_tag_commit: str,
                      compare_state: str) -> dict:
    if (cfg.get('repository') != URL or cfg.get('branch') != 'main'
            or not SHA.fullmatch(cfg.get('commit', '')) or not SHA.fullmatch(head)):
        raise ValueError('Only the fixed F5 main repository and full exact commits are allowed')
    if head == cfg['commit']:
        if compare_state != 'identical':
            raise ValueError('Inconsistent upstream comparison')
        return deepcopy(cfg)
    if compare_state != 'ahead':
        raise ValueError('Upstream rollback or divergent history requires manual review')
    version = 'main-' + head[:12]
    if latest_tag_commit == head:
        if not VERSION.fullmatch(latest_tag):
            raise ValueError('Unsafe or unsupported upstream version tag')
        version = latest_tag
    return {**cfg, 'commit': head, 'upstream_version': version}


def identity_from_files(cfg: dict, files: dict[str, bytes]) -> str:
    value = {
        'schema': 1, 'repository': cfg['repository'], 'commit': cfg['commit'],
        'upstream_version': cfg['upstream_version'],
        'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def release_identity(root: Path = ROOT, commit: str | None = None) -> str:
    """Identify package-affecting content; optional commit reads immutable Git blobs."""
    def contents(name):
        if commit:
            if not SHA.fullmatch(commit):
                raise ValueError('Identity provenance must be a full commit')
            return subprocess.check_output(['git', 'show', f'{commit}:{name}'], cwd=root)
        return (root / name).read_bytes()
    if commit:
        overlays = git('ls-tree', '-r', '--name-only', commit, '--', 'overlay', root=root).splitlines()
    else:
        overlays = sorted(p.relative_to(root).as_posix() for p in (root / 'overlay').rglob('*') if p.is_file())
    return identity_from_files(json.loads(contents('upstream.json')),
                               {name: contents(name) for name in (*IDENTITY_PATHS, *overlays)})


def validate_changed_paths(paths: list[str]) -> None:
    bad = sorted(set(paths) - DATA_PATHS)
    if bad:
        raise ValueError('Automatic synchronization cannot change code or unapproved paths: ' + ', '.join(bad))


def reconcile_retained(old: dict, catalog: dict, zh: dict) -> dict:
    active = {k: v for k, v in catalog['entries'].items() if not v.get('obsolete')}
    records = {}
    for entry in old['entries']:
        key = entry['key']
        if key in records:
            raise ValueError('Duplicate retained-English key')
        if key in active:
            if entry['source'] != active[key]['source'] or not entry.get('reason', '').strip():
                raise ValueError('Retained technical text changed; manual review required')
            # A manual Chinese translation can retire an old retention decision.
            if zh.get('entries', {}).get(key, {}).get('text') == entry['source']:
                records[key] = {**entry, 'occurrences': active[key].get('occurrences', [])}
    for key, entry in active.items():
        if zh.get('entries', {}).get(key, {}).get('text') == entry['source'] and key not in records:
            raise ValueError(f'{key}: English text has no reviewed technical-retention reason')
    return {**deepcopy(old), 'upstream_commit': catalog['upstream_commit'], 'entries': list(records.values())}


def match_release(releases: list[dict], identity: str, upstream_sha: str) -> dict | None:
    for release in releases:
        cn = release.get('target_commitish', '')
        if (isinstance(cn, str) and SHA.fullmatch(cn) and release.get('draft') is False
                and release.get('prerelease') is True
                and release.get('tag_name') == f'cn-test-{upstream_sha[:12]}-{cn[:12]}'
                and f'<!-- f5-cn-sync:v1 identity={identity} cn_commit={cn} -->' in (release.get('body') or '')):
            return release
    return None


def build_disposition(runs: list[dict], cn_sha: str) -> str:
    matches = [r for r in runs if r.get('head_sha') == cn_sha and r.get('event') == 'workflow_dispatch'
               and r.get('path', '').split('@')[0] == '.github/workflows/build.yml'
               and r.get('display_title') != 'F5 build checks']
    if any(r.get('status') != 'completed' for r in matches):
        return 'pending'
    # No release after any completed dispatch needs investigation, not a duplicate build.
    return 'blocked' if matches else 'dispatch'


class GitHub:
    """No write retries. An ambiguous mutation is reconciled by read, or stops."""
    def __init__(self, token: str):
        if not token:
            raise ValueError('The workflow-scoped GH_TOKEN is required')
        self.token = token

    def request(self, method: str, path: str, body=None, *, missing_ok=False):
        if not path.startswith('/repos/' + REPO + '/') and not (
                method == 'GET' and path.startswith('/repos/' + UPSTREAM + '/')):
            raise ValueError('API operation is outside the authorized repositories')
        if method != 'GET':
            allowed_posts = {f'/repos/{REPO}/git/trees', f'/repos/{REPO}/git/commits',
                             f'/repos/{REPO}/actions/workflows/build.yml/dispatches'}
            if method == 'PATCH':
                if (path != f'/repos/{REPO}/git/refs/heads/main' or not isinstance(body, dict)
                        or set(body) != {'sha', 'force'} or body['force'] is not False
                        or not SHA.fullmatch(body.get('sha', ''))):
                    raise ValueError('Only a full-SHA non-force main update is allowed')
            elif method != 'POST' or path not in allowed_posts:
                raise ValueError('Unapproved synchronization API mutation')
        request = Request('https://api.github.com' + path, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'Accept': 'application/vnd.github+json',
                                   'Authorization': 'Bearer ' + self.token,
                                   'Content-Type': 'application/json',
                                   'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urlopen(request, timeout=90) as response:
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            # Never print headers or response content that may contain credentials.
            raise RuntimeError(f'GitHub {method} {path}: HTTP {error.code}') from None

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def pages(self, path: str, key: str | None = None) -> list:
        output = []
        for page in range(1, 1001):
            result = self.get(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
            values = result[key] if key else result
            if not isinstance(values, list):
                raise ValueError('Unexpected paginated API response')
            output.extend(values)
            if len(values) < 100:
                return output
        raise ValueError('Pagination exceeded bounded API budget; refusing an incomplete inventory')


def validate_context(env: dict, root: Path) -> str:
    sha = env.get('GITHUB_SHA', '')
    if (env.get('GITHUB_ACTIONS') != 'true'
            or env.get('GITHUB_REPOSITORY') != REPO or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_EVENT_NAME') not in {'schedule', 'workflow_dispatch', 'push'}
            or not SHA.fullmatch(sha) or git('rev-parse', 'HEAD', root=root) != sha):
        raise ValueError('Synchronization requires the exact authorized main workflow checkout')
    if git('status', '--porcelain', '--untracked-files=all', root=root):
        raise ValueError('Synchronization starts only from a clean repository checkout')
    return sha


def validate_dispatch(env: dict) -> None:
    expected = env.get('EXPECTED_CN_SHA', '')
    if expected and (not SHA.fullmatch(expected) or expected != env.get('GITHUB_SHA')):
        raise ValueError('Build dispatch expected_sha does not equal the actual workflow commit')


def _bootstrap_match(root: Path, identity: str, api: GitHub) -> dict | None:
    known = read_json(root / 'Automation/bootstrap-release.json')
    if identity != known['identity']:
        return None
    release = api.get(f'/repos/{REPO}/releases/{known["release_id"]}')
    expected = ('id', 'tag_name', 'target_commitish', 'draft', 'prerelease')
    if any(release.get(k) != known[k] for k in expected):
        raise ValueError('Previously published baseline identity changed')
    fields = ('id', 'name', 'size', 'digest')
    actual = sorted([{k: a.get(k) for k in fields} for a in release.get('assets', [])], key=lambda a: a['id'])
    if actual != sorted(known['assets'], key=lambda a: a['id']):
        raise ValueError('Previously published baseline assets changed')
    tag = api.get(f'/repos/{REPO}/git/ref/tags/{known["tag_name"]}')
    obj = tag['object']
    for _ in range(4):
        if obj.get('type') == 'commit':
            break
        if obj.get('type') != 'tag' or not SHA.fullmatch(obj.get('sha', '')):
            raise ValueError('Unexpected bootstrap tag object')
        obj = api.get(f'/repos/{REPO}/git/tags/{obj["sha"]}')['object']
    if obj.get('type') != 'commit' or obj.get('sha') != known['target_commitish']:
        raise ValueError('Previously published baseline tag changed')
    return release

def verify_published_identity(release: dict, api: GitHub) -> None:
    """Verify tag and authenticated asset metadata against publisher's manifest."""
    cn, tag = release['target_commitish'], release['tag_name']
    obj = api.get(f'/repos/{REPO}/git/ref/tags/{tag}')['object']
    for _ in range(4):
        if obj.get('type') == 'commit':
            break
        if obj.get('type') != 'tag' or not SHA.fullmatch(obj.get('sha', '')):
            raise ValueError('Unexpected published tag object')
        obj = api.get(f'/repos/{REPO}/git/tags/{obj["sha"]}')['object']
    if obj.get('type') != 'commit' or obj.get('sha') != cn:
        raise ValueError('Published tag no longer matches its verified CN commit')
    assets = release.get('assets', [])
    if len(assets) != 3:
        raise ValueError('Published test release no longer has exactly three assets')
    hashes = {}
    for asset in assets:
        name = asset.get('name', '')
        digest = asset.get('digest', '')
        if (asset.get('state') != 'uploaded' or type(asset.get('size')) is not int or asset['size'] <= 0
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or name in hashes):
            raise ValueError('Published asset metadata is incomplete or ambiguous')
        hashes[name] = digest[7:]
    zips = [name for name in hashes if name.endswith('.zip')]
    if len(zips) != 1 or set(hashes) != {zips[0], zips[0] + '.sha256', 'build-metadata.json'}:
        raise ValueError('Published asset name set changed')
    manifest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    marker = f'<!-- f5-cn-test-gate:v1 cn_commit={cn} assets_sha256={manifest} -->'
    if marker not in (release.get('body') or ''):
        raise ValueError('Published assets no longer match the original publisher ownership manifest')


def _run(*args, root=ROOT):
    subprocess.run([str(a) for a in args], cwd=root, check=True)


def _inventory(root: Path, source: Path, catalog: dict, zh: dict, retained: dict) -> None:
    from f5_release_notes import summarize
    from loclib import iter_source_files
    stats = summarize(catalog, zh, retained, read_json(root / 'Localization/master/pending.json'))
    if stats['missing'] or stats['stale']:
        raise ValueError('Untranslated/stale catalog entries block synchronization')
    entries = {k: e for k, e in catalog['entries'].items() if not e.get('obsolete')}
    files = sorted({o['file'] for e in entries.values() for o in e.get('occurrences', [])})
    texts = [zh['entries'][k]['text'] for k in entries]
    previous = read_json(root / 'reports/coverage-inventory.json')
    previous.update({
        'upstream_commit': catalog['upstream_commit'],
        'scanned_source_files': sum(1 for _ in iter_source_files(source, read_json(root / 'Localization/scanner-rules.json'))),
        'source_files_with_catalog_occurrences': len(files), 'catalog_entries': stats['total'],
        'catalog_occurrences': sum(len(e.get('occurrences', [])) for e in entries.values()),
        'changed_display_translations': stats['changed_display_translations'],
        'retained_technical_entries': stats['retained_technical_entries'],
        'missing': stats['missing'], 'stale': stats['stale'],
        'inherited_reviewed_state': stats['reviewed'], 'machine_translated_state': stats['machine_translated'],
        'max_static_translation_utf8_bytes': max((len(s.encode()) for s in texts), default=0),
        'unique_non_ascii_codepoints': len({c for s in texts for c in s if ord(c) > 127}),
        'source_files': files,
    })
    # Historical audit counts describe the baseline review; do not inflate them.
    write_json(root / 'reports/coverage-inventory.json', previous)


def _commit_data(api: GitHub, root: Path, parent: str, upstream: str) -> str:
    paths = git('diff', '--name-only', root=root).splitlines()
    validate_changed_paths(paths)
    if not paths:
        return parent
    if git('ls-files', '--others', '--exclude-standard', root=root):
        raise ValueError('Unexpected untracked files before synchronization commit')
    if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != parent:
        raise ValueError('Main changed during preflight; a later synchronization must retry')
    tree_base = api.get(f'/repos/{REPO}/git/commits/{parent}')['tree']['sha']
    elements = []
    for name in paths:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Synchronization cannot delete files or introduce links')
        mode = git('ls-files', '-s', '--', name, root=root).split()[0]
        if mode != '100644':
            raise ValueError('Synchronization data must remain ordinary files')
        elements.append({'path': name, 'mode': mode, 'type': 'blob', 'content': path.read_text(encoding='utf-8')})
    tree = api.request('POST', f'/repos/{REPO}/git/trees', {'base_tree': tree_base, 'tree': elements})
    commit = api.request('POST', f'/repos/{REPO}/git/commits', {
        'message': f'sync: audited F5 upstream {upstream[:12]}', 'tree': tree['sha'], 'parents': [parent]})
    sha = commit['sha']
    if not SHA.fullmatch(sha):
        raise ValueError('Invalid commit response')
    if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != parent:
        raise ValueError('Main changed before fast-forward; orphan data commit was not installed')
    try:
        api.request('PATCH', f'/repos/{REPO}/git/refs/heads/main', {'sha': sha, 'force': False})
    except Exception:
        if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != sha:
            raise
    if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != sha:
        raise ValueError('Main update could not be verified')
    return sha


def synchronize(root: Path, env: dict, api: GitHub) -> dict:
    from f5_upstream_contract import load_contract, validate_config, verify_source
    parent = validate_context(env, root)
    cfg = read_json(root / 'upstream.json')
    contract = load_contract(root / 'upstream-contract.json')
    validate_config(cfg, contract)
    if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != parent:
        raise ValueError('Workflow checkout is no longer current main')
    head = api.get(f'/repos/{UPSTREAM}/commits/main')['sha']
    comparison = api.get(f'/repos/{UPSTREAM}/compare/{cfg["commit"]}...{head}')['status']
    latest = api.get(f'/repos/{UPSTREAM}/releases/latest', missing_ok=True)
    tag, tag_sha = '', ''
    if latest and not latest.get('draft') and not latest.get('prerelease'):
        tag = latest['tag_name']
        if VERSION.fullmatch(tag):
            tag_sha = api.get(f'/repos/{UPSTREAM}/commits/{tag}')['sha']
    candidate = resolve_candidate(cfg, head, tag, tag_sha, comparison)
    validate_config(candidate, contract)
    source = root / '_upstream'
    if source.exists():
        raise ValueError('Fresh synchronization checkout must not contain _upstream')
    _run('git', 'clone', '--no-checkout', '--no-tags', '--depth=1', '-c', 'core.autocrlf=false',
         '-c', 'core.eol=lf', URL, source, root=root)
    _run('git', 'fetch', '--no-tags', '--depth=1', 'origin', head, root=source)
    _run('git', 'checkout', '--detach', head, root=source)
    evidence = verify_source(source, candidate, contract)
    write_json(root / 'reports/sync-compatibility.json', evidence)
    # Diagnostics must not become commit candidates.
    _run('git', 'check-ignore', 'reports/sync-compatibility.json', root=root)
    if candidate != cfg:
        write_json(root / 'upstream.json', candidate)
        installers = read_json(root / 'Localization/installers.zh-CN.json')
        installers['upstream_commit'] = head
        write_json(root / 'Localization/installers.zh-CN.json', installers)
    _run(sys.executable, 'tools/scan_ui.py', '--source', source, '--channel', 'master',
         '--upstream-ref', candidate['upstream_version'], '--update', '--report', 'reports/sync-scan.md', root=root)
    _run(sys.executable, 'tools/check_localization.py', '--strict', '--channel', 'master', root=root)
    catalog = read_json(root / 'Localization/master/catalog.json')
    zh = read_json(root / 'Localization/zh-CN.json')
    retained = reconcile_retained(read_json(root / 'Localization/retained-English.json'), catalog, zh)
    write_json(root / 'Localization/retained-English.json', retained)
    _inventory(root, source, catalog, zh, retained)
    # Validate all output before writing GitHub state, even for a no-change day.
    _run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v', root=root)
    _run(sys.executable, 'tools/localize_f5.py', '--source', source, '--channel', 'master', root=root)
    for fixture in ('test_f5_display_runtime.py', 'test_f5_catalog_representatives.py', 'test_f5_real_display_samples.py'):
        _run(sys.executable, 'tests/' + fixture, '--repo', root, root=root)
    identity = release_identity(root)
    releases = api.pages(f'/repos/{REPO}/releases')
    published = match_release(releases, identity, head)
    if published:
        verify_published_identity(published, api)
    else:
        published = _bootstrap_match(root, identity, api)
    changed = git('diff', '--name-only', root=root).splitlines()
    validate_changed_paths(changed)
    if published and not changed:
        return {'status': 'up_to_date', 'upstream_commit': head, 'cn_commit': parent,
                'release_url': published['html_url'], 'identity': identity,
                'translation_service': 'not_configured; exact-source memory reuse with provenance preserved'}
    cn = _commit_data(api, root, parent, head)
    if published:
        return {'status': 'metadata_updated', 'upstream_commit': head, 'cn_commit': cn,
                'release_url': published['html_url'], 'identity': identity}
    # Do not rebuild around an uncertain partially-published draft.
    draft_tag = f'cn-test-{head[:12]}-{cn[:12]}'
    if any(r.get('tag_name') == draft_tag for r in releases):
        raise ValueError('An existing incomplete release requires exact-run recovery; no automatic overwrite')
    runs = api.pages(f'/repos/{REPO}/actions/workflows/build.yml/runs?event=workflow_dispatch', 'workflow_runs')
    disposition = build_disposition(runs, cn)
    if disposition == 'blocked':
        raise ValueError('A previous matching build completed without a verified release; inspect its diagnostics')
    if disposition == 'dispatch':
        if api.get(f'/repos/{REPO}/git/ref/heads/main')['object']['sha'] != cn:
            raise ValueError('Main advanced before exact-SHA build dispatch')
        api.request('POST', f'/repos/{REPO}/actions/workflows/build.yml/dispatches',
                    {'ref': 'main', 'inputs': {'expected_sha': cn, 'sync_publish': 'true'}})
    return {'status': 'build_' + ('requested' if disposition == 'dispatch' else 'pending'),
            'upstream_commit': head, 'cn_commit': cn, 'identity': identity,
            'note': 'Publication requires the same-run portable and Windows jobs plus verified package checks.'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, default=ROOT / 'reports/sync-result.json')
    parser.add_argument('--verify-dispatch', action='store_true')
    args = parser.parse_args(argv)
    if args.verify_dispatch:
        validate_dispatch(dict(os.environ))
        print('Exact build dispatch input verified')
        return 0
    result = synchronize(ROOT, dict(os.environ), GitHub(os.environ.get('GH_TOKEN', '')))
    write_json(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Synchronization stopped: {exc}', file=sys.stderr)
        raise SystemExit(1)
