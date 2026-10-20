#!/usr/bin/env python3
"""Publish one explicitly triggered, verified F5 CN prerelease. Fail closed.

No credential discovery, deletion, tag update, asset replacement, or general
release interface is provided. Authentication belongs to gh via the workflow's
short-lived GH_TOKEN. All external operations are isolated in GitHub.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN'
TAG = 'v0.1.32-cn-test.1'
TRIGGER = 'release: publish ' + TAG
UPSTREAM = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
UPSTREAM_REPOSITORY = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'
HYBRID_HASH = '3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037'
API_ROOT = 'repos/' + REPOSITORY + '/'
SCRIPTS = ('setup_windows.bat', 'setup_linux.sh', 'Streamlined_fetcher_windows.bat', 'get_streamline.ps1')
PACKAGED_SCRIPTS = ('setup_windows.bat', 'setup_linux.sh', 'get_streamline.ps1')
REQUIRED = ('OptiScaler.dll', 'nvngx.dll_dlssnr.dll', 'BUILD-INFO.CN.json', 'SHA256SUMS.txt',
            'README.CN.zh-CN.md', 'UPSTREAM.CN.md', 'OptiScalerCN.ini', 'LICENSE', 'README.md',
            'INSTALL-DLSSNR.md', 'OptiScaler.ini', 'setup_windows.bat', 'setup_linux.sh',
            'get_streamline.ps1', 'redist/streamline/manifest.json',
            '!! EXTRACT ALL FILES TO GAME FOLDER !!', 'Licenses/HybridSource/LICENSE')


class GateError(RuntimeError):
    """A missing proof or an unexpected state must stop publishing."""


class GitHubError(GateError):
    """An API operation failed or its result is uncertain; read before retrying."""


def require(condition, message):
    if not condition:
        raise GateError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def object_json(data, name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'Duplicate JSON key in {name}: {key}')
            result[key] = value
        return result
    try:
        result = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise GateError(f'Invalid UTF-8 JSON: {name}') from exc
    require(isinstance(result, dict), f'Expected JSON object: {name}')
    return result


def validate_context(env, event):
    required = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY,
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
                'BUILD_RESULT': 'success', 'PORTABLE_RESULT': 'success'}
    for key, value in required.items():
        require(env.get(key) == value, f'Release gate rejected {key}')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Full current commit SHA required')
    for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        require(re.fullmatch('[1-9][0-9]*', env.get(key, '')), f'Invalid {key}')
    require(bool(env.get('GH_TOKEN')), 'Only nonempty workflow-provided ephemeral GH_TOKEN authentication is supported')
    require(env.get('GITHUB_SERVER_URL', 'https://github.com') == 'https://github.com', 'Unexpected GitHub server')
    require(env.get('GH_HOST', 'github.com') == 'github.com', 'Unexpected gh host')
    require(isinstance(event, dict) and event.get('repository', {}).get('full_name') == REPOSITORY,
            'Push event repository mismatch')
    require(event.get('ref') == 'refs/heads/main' and event.get('after') == sha and event.get('deleted') is False,
            'Push event ref or SHA mismatch')
    head = event.get('head_commit') or {}
    require(head.get('id') == sha and head.get('message') == TRIGGER,
            'Head commit must have the exact one-line release trigger message')
    return {'sha': sha, 'run_id': env['GITHUB_RUN_ID'], 'attempt': env['GITHUB_RUN_ATTEMPT']}


def safe_name(name):
    require(isinstance(name, str) and name and not re.search(r'(^/|[\\:\x00-\x1f])', name), 'Unsafe ZIP name')
    parts = name.rstrip('/').split('/')
    for part in parts:
        require(part not in ('', '.', '..') and not re.search(r'[. ]$|[<>"|?*]', part)
                and not re.match(r'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part),
                f'Unsafe Windows ZIP component: {name}')


def pe64(data, name):
    require(len(data) >= 256 and data[:2] == b'MZ', f'Not a PE DLL: {name}')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    require(offset <= len(data) - 96 and data[offset:offset + 4] == b'PE\0\0', f'Invalid PE header: {name}')
    require(struct.unpack_from('<H', data, offset + 4)[0] == 0x8664
            and struct.unpack_from('<H', data, offset + 24)[0] == 0x20b
            and struct.unpack_from('<H', data, offset + 22)[0] & 0x2000,
            f'Expected x64 PE32+ DLL: {name}')


def verify_artifact(directory, sha, catalog_path=ROOT / 'Localization/installers.zh-CN.json'):
    """Validate downloaded same-run package bytes without extracting any ZIP."""
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'Missing or linked artifact directory')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Invalid CN commit')
    version = 'v0.1.32-cn-' + sha[:12]
    name = f'OptiScaler-F5-DLSSNR-Multipass-CN-{version}-{UPSTREAM[:12]}.zip'
    expected = {name, name + '.sha256', 'build-metadata.json'}
    items = list(directory.iterdir())
    require({p.name for p in items} == expected and all(p.is_file() and not p.is_symlink() for p in items),
            'Artifact must contain exactly the package, checksum sidecar and build metadata')
    paths = {p.name: p for p in items}
    require(paths['build-metadata.json'].stat().st_size <= 4 * 1024 * 1024, 'Build metadata exceeds size budget')
    require(paths[name + '.sha256'].stat().st_size <= 1024, 'Checksum sidecar exceeds size budget')
    require(0 < paths[name].stat().st_size <= 2 * 1024**3, 'Package exceeds size budget')
    metadata = object_json(paths['build-metadata.json'].read_bytes(), 'build-metadata.json')
    actual = file_hash(paths[name])
    require(metadata.get('package') == name and metadata.get('sha256') == actual, 'Package SHA256 or name mismatch')
    require(paths[name + '.sha256'].read_bytes() in
            ((actual + ' *' + name + '\n').encode(), (actual + ' *' + name + '\r\n').encode()),
            'Package checksum sidecar mismatch')
    identity = {'schema': 1, 'cn_commit': sha, 'upstream_commit': UPSTREAM, 'upstream_version': 'v0.1.32',
                'upstream_repository': UPSTREAM_REPOSITORY, 'package_version': version,
                'variant': 'downloader-only', 'configuration': 'Release', 'platform': 'x64', 'toolset': 'v143',
                'hybrid_archive_sha256': HYBRID_HASH, 'game_runtime_validation': 'not performed by this workflow'}
    for key, value in identity.items():
        require(metadata.get(key) == value, f'Unexpected build identity: {key}')
    require(isinstance(metadata.get('recursive_submodules'), list) and metadata['recursive_submodules']
            and all(isinstance(x, str) and re.match(r'^ [0-9a-f]{40} [^\r\n]+$', x)
                    for x in metadata['recursive_submodules']), 'Recursive submodule evidence missing')
    require(all(isinstance(metadata.get(key), str) and metadata[key]
                for key in ('msbuild_version', 'built_at_utc', 'packaged_at_utc')), 'Toolchain/timestamp evidence missing')
    hashes = {}
    captured = {}
    capture = set(REQUIRED)
    with zipfile.ZipFile(paths[name]) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 10000, 'Invalid ZIP entry count')
        seen = set()
        total = 0
        for entry in entries:
            safe_name(entry.filename)
            key = entry.filename.rstrip('/').casefold()
            require(key not in seen, 'Duplicate/case-colliding ZIP entry')
            seen.add(key)
            mode = (entry.external_attr >> 16) & 0xf000
            require(mode in (0, 0x4000, 0x8000), 'ZIP link or special file forbidden')
            require(not entry.flag_bits & 1, 'Encrypted ZIP entry forbidden')
            total += entry.file_size
            require(entry.file_size <= 1024**3 and total <= 2 * 1024**3, 'ZIP expands beyond audited size budget')
            if entry.is_dir():
                continue
            base = entry.filename.rsplit('/', 1)[-1]
            require(not re.search(r'(?i)^(nvngx_dlss.*|sl\..*)\.dll$|\.(pdb|exp|lib|ilk|asi)$|latewarp|nrtrace', base)
                    and base.lower() != 'dlssg_sm86.dll', f'Forbidden downloader-only payload: {base}')
            with archive.open(entry) as stream:
                hashes[entry.filename] = hashlib.file_digest(stream, 'sha256').hexdigest()
            if entry.filename in capture:
                # PE headers need only 256 bytes; other captured inputs are bounded text.
                with archive.open(entry) as stream:
                    if entry.filename in ('OptiScaler.dll', 'nvngx.dll_dlssnr.dll'):
                        header = stream.read(4096)
                        require(len(header) >= 64, 'Truncated PE file')
                        offset = struct.unpack_from('<I', header, 0x3c)[0]
                        require(offset <= 1024 * 1024, 'Unreasonable PE header offset')
                        if offset + 96 > len(header):
                            header += stream.read(offset + 96 - len(header))
                        captured[entry.filename] = header
                    else:
                        require(entry.file_size <= 4 * 1024 * 1024, 'Text package entry exceeds size budget')
                        captured[entry.filename] = stream.read()
        require(set(REQUIRED).issubset(hashes), 'Required package file missing')
        # Reject file/parent collisions even without explicit directory entries.
        file_names = {name.casefold() for name in hashes}
        for filename in hashes:
            parts = filename.casefold().split('/')
            require(not any('/'.join(parts[:i]) in file_names
                            for i in range(1, len(parts))), 'ZIP file/directory collision')
    require(type(metadata.get('verified_archive_files')) is int and metadata['verified_archive_files'] == len(hashes),
            'Archive file-count evidence mismatch')
    inner = object_json(captured['BUILD-INFO.CN.json'], 'BUILD-INFO.CN.json')
    require(inner == {k: v for k, v in metadata.items() if k not in ('package', 'sha256', 'verified_archive_files')},
            'Inner/outer build metadata mismatch')
    checksums = {}
    try:
        lines = captured['SHA256SUMS.txt'].decode('utf-8-sig').splitlines()
    except UnicodeError as exc:
        raise GateError('Invalid checksum manifest encoding') from exc
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64}) \*(.+)', line)
        require(match and match[2] not in checksums, 'Invalid or duplicate internal checksum')
        checksums[match[2]] = match[1]
    require(checksums == {k: v for k, v in hashes.items() if k != 'SHA256SUMS.txt'}, 'Internal checksum manifest mismatch')
    binaries = metadata.get('binaries')
    require(isinstance(binaries, list) and len(binaries) == 2, 'Expected exactly two locally compiled binary records')
    binary_hashes = {entry.get('name'): entry.get('sha256') for entry in binaries if isinstance(entry, dict)}
    require(set(binary_hashes) == {'OptiScaler.dll', 'nvngx.dll_dlssnr.dll'}, 'Compiled DLL evidence names mismatch')
    for binary, expected_hash in binary_hashes.items():
        require(hashes[binary] == expected_hash, f'Compiled DLL hash mismatch: {binary}')
        pe64(captured[binary], binary)
    hybrid = metadata.get('hybrid_assets')
    require(isinstance(hybrid, list) and len(hybrid) == 15, 'Expected 15 hybrid resources')
    hybrid_paths = set()
    for item in hybrid:
        require(isinstance(item, dict), 'Invalid hybrid resource record')
        safe_name(item.get('path'))
        resource = 'OptiScaler/nvfp4/hybrid/' + item['path']
        require(resource not in hybrid_paths and hashes.get(resource) == item.get('sha256'), 'Hybrid resource mismatch')
        hybrid_paths.add(resource)
    catalog = object_json(Path(catalog_path).read_bytes(), 'installer catalog')
    records = catalog.get('scripts', [])
    require(catalog.get('upstream_commit') == UPSTREAM and tuple(x.get('path') for x in records) == SCRIPTS,
            'Installer catalog pin/entrypoints mismatch')
    require(tuple(x['path'] for x in records if x.get('packaged') is True) == PACKAGED_SCRIPTS,
            'Installer packaging contract mismatch')
    for record in records:
        if not record.get('packaged'):
            continue
        script = record['path']
        normalized = captured[script].decode('utf-8-sig').replace('\r\n', '\n')
        require(re.search('[\u4e00-\u9fff]', normalized)
                and sha256(normalized.encode()) == record.get('localized_sha256'), f'Chinese installer fingerprint mismatch: {script}')
    manifest = catalog.get('redist', {})
    require(manifest.get('path') == 'redist/streamline/manifest.json'
            and hashes[manifest['path']] == manifest.get('sha256'), 'Original vendor manifest changed')
    require(re.search('[\u4e00-\u9fff]', captured['README.CN.zh-CN.md'].decode('utf-8-sig')),
            'Chinese installation guide missing')
    require(re.search(r'(?m)^Language\s*=\s*zh-CN\s*$', captured['OptiScalerCN.ini'].decode('utf-8-sig')),
            'Default Chinese language setting missing')
    return {'assets': paths, 'hashes': {n: file_hash(p) for n, p in paths.items()}, 'metadata': metadata}


class GitHub:
    """Fixed-host gh transport. Never prints subprocess output or reads secrets."""
    def _run(self, command, payload=None, output=None):
        try:
            result = subprocess.run(command, input=payload, stdout=output or subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=False, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError('GitHub operation outcome uncertain; inspect remote state before retrying') from exc
        if result.returncode:
            raise GitHubError('GitHub operation failed; no automatic mutation retry')
        return result.stdout

    def api(self, method, path, payload=None):
        require(method in ('GET', 'POST', 'PATCH'), 'Destructive API methods forbidden')
        require(path.startswith(API_ROOT) and '://' not in path and '..' not in path, 'API destination outside fixed repository')
        if method == 'POST':
            require(path == API_ROOT + 'releases', 'Only draft creation is allowed')
            require(payload and payload.get('tag_name') == TAG and payload.get('draft') is True
                    and payload.get('prerelease') is True and payload.get('make_latest') == 'false', 'Unsafe release creation')
        if method == 'PATCH':
            require(re.fullmatch(re.escape(API_ROOT) + r'releases/[1-9][0-9]*', path)
                    and payload == {'draft': False, 'prerelease': True, 'make_latest': 'false'}, 'Only draft publication is allowed')
        command = ['gh', 'api', '--hostname', 'github.com', '--method', method,
                   '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28', path]
        encoded = None
        if payload is not None:
            command += ['--input', '-']
            encoded = json.dumps(payload, ensure_ascii=False).encode()
        data = self._run(command, encoded)
        try:
            return json.loads(data)
        except (TypeError, ValueError) as exc:
            raise GitHubError('GitHub returned invalid JSON; inspect state before retrying') from exc

    def upload(self, path):
        self._run(['gh', 'release', 'upload', TAG, str(path), '--repo', 'github.com/' + REPOSITORY])

    def download(self, asset_id, target):
        require(type(asset_id) is int and asset_id > 0, 'Invalid release asset ID')
        with target.open('xb') as output:
            self._run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                       '-H', 'Accept: application/octet-stream',
                       API_ROOT + f'releases/assets/{asset_id}'], output=output)


def listing(github, endpoint, key=None):
    result = []
    for page in range(1, 101):
        data = github.api('GET', API_ROOT + endpoint + f'?per_page=100&page={page}')
        batch = data.get(key) if key and isinstance(data, dict) else data
        require(isinstance(batch, list), 'Malformed paginated GitHub response')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise GateError('GitHub response exceeds audited pagination limit')


def verify_run(github, context):
    run = github.api('GET', API_ROOT + 'actions/runs/' + context['run_id'])
    require(run.get('id') == int(context['run_id']) and run.get('event') == 'push'
            and run.get('head_sha') == context['sha'] and run.get('head_branch') == 'main'
            and run.get('path') == '.github/workflows/build.yml'
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('run_attempt') == int(context['attempt']), 'Same-run provenance mismatch')
    jobs = listing(github, f'actions/runs/{context["run_id"]}/attempts/{context["attempt"]}/jobs', 'jobs')
    for name in ('build', 'portable-contracts'):
        matches = [job for job in jobs if job.get('name') == name]
        require(len(matches) == 1 and matches[0].get('status') == 'completed'
                and matches[0].get('conclusion') == 'success'
                and matches[0].get('run_id') == int(context['run_id']), f'Required successful same-run job missing: {name}')
    verify_main(github, context)


def verify_main(github, context):
    main = github.api('GET', API_ROOT + 'git/ref/heads/main')
    require(main.get('object', {}).get('type') == 'commit' and main['object'].get('sha') == context['sha'],
            'main advanced or changed; do not release a stale trigger commit')


def tag_commit(github):
    refs = github.api('GET', API_ROOT + 'git/matching-refs/tags/' + TAG)
    require(isinstance(refs, list), 'Unexpected tag response')
    exact = [ref for ref in refs if ref.get('ref') == 'refs/tags/' + TAG]
    require(len(exact) <= 1, 'Duplicate release tag')
    if not exact:
        return None
    obj = exact[0].get('object', {})
    for _ in range(6):
        require(re.fullmatch('[0-9a-f]{40}', obj.get('sha', '')), 'Invalid tag object SHA')
        if obj.get('type') == 'commit':
            return obj['sha']
        require(obj.get('type') == 'tag', 'Tag does not resolve to commit')
        obj = github.api('GET', API_ROOT + 'git/tags/' + obj['sha']).get('object', {})
    raise GateError('Excessive annotated-tag nesting')


def find_release(github):
    releases = listing(github, 'releases')  # Includes drafts for contents:write; tag lookup alone does not.
    exact = [release for release in releases if release.get('tag_name') == TAG]
    require(len(exact) <= 1, 'More than one release uses the fixed tag')
    return exact[0] if exact else None


def ownership_marker(package, context):
    manifest = sha256(json.dumps(package['hashes'], sort_keys=True, separators=(',', ':')).encode())
    return f'<!-- f5-cn-test-gate:v1 cn_commit={context["sha"]} assets_sha256={manifest} -->'


def release_payload(package, context):
    meta = package['metadata']
    body = f'''## F5 简体中文测试版

这是社区测试版（Pre-release），固定上游 F5 v0.1.32。请先备份原安装，勿用于带反作弊保护的多人游戏。

- 中文仓库提交：`{context['sha']}`
- 固定上游提交：`{UPSTREAM}`
- [本次构建与检查](https://github.com/{REPOSITORY}/actions/runs/{context['run_id']})
- 安装包：`{meta['package']}`
- 安装包 SHA-256：`{meta['sha256']}`

### 已完成的发布门槛

同一次工作流中的可移植契约测试和 Windows MSVC v143 Release x64 编译成功；安装包、内外元数据、逐文件 SHA-256、x64 DLL 标头和中文安装脚本指纹通过检查。发布前还会下载并核对上传资产的实际字节。

### 测试范围与安装提醒

- Windows 编译成功不等于游戏内运行、画面或中文排版通过。没有执行实际 GPU/游戏验证，也没有确认全部主题、缩放、GPU 或驱动组合。
- 本包采用 downloader-only 方式，不包含专有 `nvngx_dlssnr.dll`，也不预打包可选 NVIDIA DLSS/Streamline、Ampere MFG 或外部 vendor-neutral 组件。需要的专有模型/运行库请按固定上游指南另行取得并核验，许可由使用者自行确认。
- 中文菜单需要系统已安装或自行提供兼容且覆盖词库的中文字体；包内不附带 Windows 字体，字体不可用时会回退英文。
- 下载 ZIP 及同名 `.sha256`，校验后完整解压到游戏 EXE 目录。中文安装入口为 `setup_windows.bat`，详细步骤见包内 `README.CN.zh-CN.md`。保留原始许可和署名。
- 请用游戏名、GPU、驱动、渲染 API、语言/字体/主题/缩放、截图及复现步骤反馈问题；分享日志前检查个人路径。

[中文说明](https://github.com/{REPOSITORY}/blob/{context['sha']}/README.zh-CN.md) · [固定上游安装指南](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/blob/{UPSTREAM}/INSTALL-DLSSNR.md)

{ownership_marker(package, context)}
'''
    return {'tag_name': TAG, 'target_commitish': context['sha'], 'name': 'OptiScaler F5 简体中文测试版 ' + TAG,
            'body': body, 'draft': True, 'prerelease': True, 'make_latest': 'false', 'generate_release_notes': False}


def verify_release_header(release, package, context, tag):
    require(isinstance(release, dict) and type(release.get('id')) is int and release['id'] > 0, 'Invalid release ID')
    require(release.get('tag_name') == TAG and release.get('target_commitish') == context['sha']
            and release.get('prerelease') is True and type(release.get('draft')) is bool,
            'Existing release target/type conflicts; nothing will be replaced')
    require(ownership_marker(package, context) in (release.get('body') or ''), 'Existing release ownership/asset manifest differs')
    require(tag in (None, context['sha']), 'Existing tag points elsewhere; it will not be updated')
    require(release['draft'] or tag == context['sha'], 'Published release tag does not resolve to verified commit')


def verify_remote_assets(github, release, package, complete=False):
    assets = listing(github, f'releases/{release["id"]}/assets')
    names = [asset.get('name') for asset in assets]
    require(len(set(names)) == len(names) and set(names).issubset(package['assets']), 'Unexpected or duplicate existing assets')
    if complete:
        require(set(names) == set(package['assets']), 'Release assets are incomplete')
    with tempfile.TemporaryDirectory(prefix='f5-release-verify-') as tmp:
        for asset in assets:
            name = asset['name']
            expected = package['hashes'][name]
            require(asset.get('state') == 'uploaded' and asset.get('size') == package['assets'][name].stat().st_size,
                    f'Existing asset state/size conflict: {name}')
            # When the API supplies its digest, require it as a second independent check.
            require(asset.get('digest') in (None, 'sha256:' + expected), f'Existing asset digest conflict: {name}')
            target = Path(tmp) / name
            github.download(asset.get('id'), target)
            require(target.is_file() and not target.is_symlink() and file_hash(target) == expected,
                    f'Remote asset byte hash mismatch: {name}')
    return set(names)


def publish(package, context, github):
    verify_run(github, context)
    release = find_release(github)
    tag = tag_commit(github)
    if release is None:
        require(tag is None, 'A tag already exists without this verified release; refusing to reuse it')
        try:
            github.api('POST', API_ROOT + 'releases', release_payload(package, context))
        except GitHubError:
            # A timeout can mean the draft was created. Never issue a second POST blindly.
            release = find_release(github)
            require(release is not None, 'Draft creation unresolved; inspect remote state before rerunning')
        else:
            release = find_release(github)
        tag = tag_commit(github)
    verify_release_header(release, package, context, tag)
    existing = verify_remote_assets(github, release, package, complete=not release['draft'])
    if not release['draft']:
        print('Already published: exact verified commit and assets; no changes made.')
        return f'https://github.com/{REPOSITORY}/releases/tag/{TAG}'
    for name, path in sorted(package['assets'].items()):
        if name in existing:
            continue
        require(file_hash(path) == package['hashes'][name], 'Local artifact changed after verification')
        try:
            github.upload(path)  # No --clobber: an existing asset is never replaced.
        except GitHubError:
            # Re-read and verify exact bytes. If absent/partial/conflicting, fail and keep the draft.
            current = find_release(github)
            verify_release_header(current, package, context, tag_commit(github))
            require(current['id'] == release['id'] and current['draft'], 'Release changed during upload')
            observed = verify_remote_assets(github, current, package)
            require(name in observed, 'Upload unresolved; draft retained for a state-checked rerun')
    release_after = find_release(github)
    verify_release_header(release_after, package, context, tag_commit(github))
    require(release_after['id'] == release['id'] and release_after['draft'], 'Draft changed during uploads')
    verify_remote_assets(github, release_after, package, complete=True)
    verify_main(github, context)
    try:
        github.api('PATCH', API_ROOT + f'releases/{release["id"]}',
                   {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    except GitHubError:
        # Only the subsequent read decides whether publication actually succeeded.
        pass
    published = find_release(github)
    verify_release_header(published, package, context, tag_commit(github))
    require(published['id'] == release['id'] and not published['draft'], 'Publication unresolved; draft retained, no blind retry')
    verify_remote_assets(github, published, package, complete=True)
    return f'https://github.com/{REPOSITORY}/releases/tag/{TAG}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, default=ROOT / 'release-artifact')
    args = parser.parse_args()
    try:
        event_path = os.environ.get('GITHUB_EVENT_PATH')
        require(event_path, 'Missing GitHub push event payload')
        context = validate_context(os.environ, object_json(Path(event_path).read_bytes(), 'push event'))
        require(args.artifact_dir.absolute() == ROOT / 'release-artifact', 'Only same-run release-artifact directory is allowed')
        package = verify_artifact(args.artifact_dir, context['sha'])
        print(publish(package, context, GitHub()))
    except (GateError, OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f'Test release blocked: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
