"""Pinned F5Low kit and release checks. Reads binary data; never loads DLLs.

The immutable upstream packager performs the Windows Authenticode/version
checks. This module adds an exact seven-file contract, retains all notices,
and makes the two release-default changes only AFTER its auto-value checks.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import zipfile

KIT_VERSION = '1.1.0.140'
KIT_URL = 'https://github.com/janblade/f5low-fg/releases/download/v1.1.0.140/f5low-kit-1.1.0.140%2B1f17d38.zip'
KIT_SHA256 = '97fa6fb53a2278dfc651e4de2b2201f399f40ce49474b5f8199a2e5794d87f56'
SOURCE_REPOSITORY = 'https://github.com/janblade/f5low-fg'
SOURCE_COMMIT = '1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a'
INTEL_VERSION = '1.3.4.95'
FILE_SHA256 = {
    'f5low.dll': '0993352a97a05537a88bd1d0266cb62ae581f219b75fc588fbc15eeeacb48fa4',
    'libxess_fg.dll': '752b1491350a29fb2850fa4d0d14f62d79980e0b3cd067d147bb2469c1ec3182',
    'LICENSE': '1ecec4c8ae6cd206ecab7be3457953616a5d497dc438d53bc726287724f77a58',
    'XeSS_LICENSE.txt': '784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df',
    'zstd_LICENSE.txt': 'd3baadc2e1dd7a7e0b483633e6b39743c16a16f28d696baff507fcd451f3d4ad',
    'README-KIT.txt': 'b34da9e444ca20d6157105722d3bfae64f1d996218b8d37289687e4c199d30f0',
    'kit_hashes.txt': '02ef995f35e19d69647005e93b7cd485d8da3b5e50901fb91e4520e6bf2c32d4',
}
FILE_SIZES = {'f5low.dll': 6350848, 'libxess_fg.dll': 22866056, 'LICENSE': 37871,
              'XeSS_LICENSE.txt': 4194, 'zstd_LICENSE.txt': 1579,
              'README-KIT.txt': 1596, 'kit_hashes.txt': 484}
STAGED_PATHS = {
    'f5low.dll': 'OptiScaler/plugins/f5low.dll',
    'libxess_fg.dll': 'OptiScaler/libxess_fg.dll',
    'LICENSE': 'Licenses/f5low_LICENSE.txt',
    'XeSS_LICENSE.txt': 'Licenses/XeSS_LICENSE.txt',
    'zstd_LICENSE.txt': 'Licenses/f5low_zstd_LICENSE.txt',
    'README-KIT.txt': 'Licenses/f5low_README-KIT.txt',
    'kit_hashes.txt': 'Licenses/f5low_kit_hashes.txt',
}
DEFAULTS = {b'FGOutput': (b'FrameGen', b'f5low'), b'FrameGenerator': (b'F5Low', b'xefg_tensor')}


def expected_metadata() -> dict:
    """Trusted release identity, never populated from artifact-provided claims."""
    return {
        'version': KIT_VERSION, 'archive_url': KIT_URL, 'archive_sha256': KIT_SHA256,
        'source_repository': SOURCE_REPOSITORY, 'source_commit': SOURCE_COMMIT,
        'intel_version': INTEL_VERSION,
        'files': [{'path': name, 'sha256': FILE_SHA256[name], 'size': FILE_SIZES[name]}
                  for name in sorted(FILE_SHA256)],
    }


def _regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Missing or linked regular file: {path}')


def _safe_zip_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if not entries or len(entries) > 10000:
        raise ValueError('Invalid ZIP entry count')
    seen = set()
    result = {}
    total = 0
    for entry in entries:
        name = entry.orig_filename
        parts = name.rstrip('/').split('/')
        if (name != entry.filename or re.search(r'[\\:\x00-\x1f]', name)
                or any(not part or part in ('.', '..') or re.search(r'[. ]$|[<>"|?*]', part)
                       or re.match(r'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part)
                       for part in parts)):
            raise ValueError(f'Unsafe ZIP path: {name!r}')
        normalized = name.rstrip('/').casefold()
        if normalized in seen:
            raise ValueError(f'Duplicate ZIP path: {name}')
        seen.add(normalized)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
            raise ValueError(f'Linked, special or encrypted ZIP member: {name}')
        total += entry.file_size
        if entry.file_size > 1024 ** 3 or total > 2 * 1024 ** 3:
            raise ValueError('ZIP expands beyond the audited size budget')
        result[name] = entry
    return result


def _verify_file(name: str, data: bytes) -> None:
    if len(data) != FILE_SIZES[name] or hashlib.sha256(data).hexdigest() != FILE_SHA256[name]:
        raise ValueError(f'Pinned F5Low file size/SHA256 mismatch: {name}')


def read_verified_kit(path: Path) -> tuple[dict[str, bytes], dict]:
    """Check the fixed official ZIP completely before the upstream extractor runs."""
    path = Path(path)
    _regular_file(path)
    if path.stat().st_size > 64 * 1024 ** 2:
        raise ValueError('F5Low kit archive exceeds size budget')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != KIT_SHA256:
        raise ValueError('Pinned F5Low archive SHA256 mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = _safe_zip_entries(archive)
        if set(entries) != set(FILE_SHA256):
            raise ValueError('F5Low kit must contain exactly the seven pinned root files')
        for name, entry in entries.items():
            if entry.file_size != FILE_SIZES[name] or entry.is_dir():
                raise ValueError(f'F5Low kit size mismatch: {name}')
        files = {name: archive.read(entry) for name, entry in entries.items()}
    for name, data in files.items():
        _verify_file(name, data)
    listed = {}
    for line in files['kit_hashes.txt'].decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([^\s/\\]+)', line)
        if not match or match[2] in listed:
            raise ValueError('Malformed or duplicate F5Low kit checksum entry')
        listed[match[2]] = match[1]
    if listed != {name: value for name, value in FILE_SHA256.items() if name != 'kit_hashes.txt'}:
        raise ValueError('F5Low kit internal checksum manifest differs from pinned files')
    readme = files['README-KIT.txt'].decode('utf-8')
    if SOURCE_REPOSITORY not in readme or f'commit {SOURCE_COMMIT}' not in readme:
        raise ValueError('F5Low source attribution missing')
    return files, expected_metadata()


def _ini_lines(data: bytes, *, require_auto: bool) -> tuple[list[bytes], dict[bytes, int]]:
    lines = data.splitlines(keepends=True)
    section = b''
    sections = set()
    found = {}
    target_sections = {value[0].lower() for value in DEFAULTS.values()}
    canonical_keys = {key.lower(): key for key in DEFAULTS}
    for index, line in enumerate(lines):
        text = line.rstrip(b'\r\n')
        if index == 0:
            text = text.removeprefix(b'\xef\xbb\xbf')
        section_match = re.fullmatch(rb'\[([^]\r\n]+)\][ \t]*(?:[;#].*)?', text.strip())
        if section_match:
            section = section_match[1]
            if section.lower() in target_sections:
                if section.lower() in sections:
                    raise ValueError('Duplicate F5Low defaults INI section')
                sections.add(section.lower())
            continue
        match = re.match(rb'^[ \t]*(FGOutput|FrameGenerator)[ \t]*=', text, re.I)
        if match:
            key = canonical_keys[match[1].lower()]
            expected_section, final_value = DEFAULTS[key]
            expected = b'auto' if require_auto else final_value
            if key in found or section != expected_section or text != key + b'=' + expected:
                raise ValueError(f'INI must have exactly one {key.decode()}={expected.decode()} in [{expected_section.decode()}]')
            found[key] = index
    if set(found) != set(DEFAULTS):
        raise ValueError('Required F5Low release defaults are missing')
    return lines, found


def apply_release_defaults(data: bytes) -> bytes:
    """Byte-preserving, fail-closed rewrite of only the two checked auto values."""
    lines, found = _ini_lines(data, require_auto=True)
    for key, index in found.items():
        old = key + b'=auto'
        lines[index] = key + b'=' + DEFAULTS[key][1] + lines[index][len(old):]
    return b''.join(lines)


def _stage_files(stage: Path) -> dict[str, Path]:
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError('Missing or linked F5Low package stage')
    files = {}
    seen = set()
    for path in stage.rglob('*'):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError(f'Linked or special package payload: {path}')
        relative = path.relative_to(stage).as_posix()
        if relative.casefold() in seen:
            raise ValueError(f'Case-colliding package payload: {relative}')
        seen.add(relative.casefold())
        if path.is_file():
            files[relative] = path
    return files


def _verify_payload_paths(names) -> None:
    for name in names:
        lower = name.casefold()
        if lower.rsplit('/', 1)[-1] in ('f5low.dll', 'libxess_fg.dll'):
            if name not in (STAGED_PATHS['f5low.dll'], STAGED_PATHS['libxess_fg.dll']):
                raise ValueError(f'Unexpected F5Low DLL path: {name}')
        if lower.startswith('optiscaler/plugins/') and name != STAGED_PATHS['f5low.dll']:
            raise ValueError(f'Unknown F5Low plugin payload: {name}')


def finalize_stage(stage: Path, archive_path: Path) -> dict:
    """Verify upstream staging, retain its kit manifest, then apply release defaults."""
    files, metadata = read_verified_kit(archive_path)
    stage = Path(stage)
    staged = _stage_files(stage)
    _verify_payload_paths(staged)
    manifest_path = STAGED_PATHS['kit_hashes.txt']
    if manifest_path in staged:
        raise ValueError('F5Low finalization output already exists')
    for name, destination in STAGED_PATHS.items():
        if name == 'kit_hashes.txt':
            continue
        if destination not in staged:
            raise ValueError(f'Upstream packager omitted F5Low file: {destination}')
        _verify_file(name, staged[destination].read_bytes())
    if 'OptiScaler.ini' not in staged:
        raise ValueError('Upstream package has no OptiScaler.ini')
    ini = apply_release_defaults(staged['OptiScaler.ini'].read_bytes())
    # All checks precede either write; no source checkout or DLL is modified.
    with (stage / manifest_path).open('xb') as output:
        output.write(files['kit_hashes.txt'])
    staged['OptiScaler.ini'].write_bytes(ini)
    return metadata


def _verify_metadata(metadata: dict) -> None:
    if (not isinstance(metadata, dict) or metadata.get('f5low_kit_included') is not True
            or metadata.get('f5low_kit') != expected_metadata()):
        raise ValueError('F5Low release metadata differs from the pinned kit identity')


def _verify_release(read, names, metadata: dict) -> None:
    _verify_metadata(metadata)
    _verify_payload_paths(names)
    required = set(STAGED_PATHS.values()) | {'OptiScaler.ini', 'BUILD-INFO.CN.json'}
    if not required <= set(names):
        raise ValueError('F5Low package is missing required files or notices')
    for name, destination in STAGED_PATHS.items():
        _verify_file(name, read(destination))
    _ini_lines(read('OptiScaler.ini'), require_auto=False)
    _verify_metadata(json.loads(read('BUILD-INFO.CN.json').decode('utf-8-sig')))


def verify_staged_f5low(stage: Path, metadata: dict) -> None:
    """Publisher/packager gate against the repository's own fixed kit contract."""
    staged = _stage_files(Path(stage))
    _verify_release(lambda name: staged[name].read_bytes(), staged, metadata)


def verify_package_f5low(archive_path: Path, metadata: dict) -> None:
    """Check shipped bytes and metadata, not just the archive's self-reported hashes."""
    _regular_file(Path(archive_path))
    with zipfile.ZipFile(archive_path) as archive:
        entries = _safe_zip_entries(archive)
        files = {name: entry for name, entry in entries.items() if not entry.is_dir()}
        # Bound allocations before reading the exact pinned files and small text inputs.
        for name, destination in STAGED_PATHS.items():
            if destination not in files or files[destination].file_size != FILE_SIZES[name]:
                raise ValueError(f'Missing or incorrectly sized F5Low package file: {destination}')
        for name in ('OptiScaler.ini', 'BUILD-INFO.CN.json'):
            if name not in files or files[name].file_size > 1024 ** 2:
                raise ValueError(f'Missing or oversized F5Low package metadata: {name}')
        _verify_release(lambda name: archive.read(files[name]), files, metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.manifest.exists() or args.manifest.is_symlink():
        raise ValueError('F5Low manifest output already exists')
    metadata = finalize_stage(args.stage, args.archive) if args.stage else read_verified_kit(args.archive)[1]
    with args.manifest.open('x', encoding='utf-8') as output:
        json.dump(metadata, output, indent=2)
        output.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
