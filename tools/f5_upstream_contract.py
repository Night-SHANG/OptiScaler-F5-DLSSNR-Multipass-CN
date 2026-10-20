#!/usr/bin/env python3
"""Read-only, fail-closed F5 upstream compatibility evidence.

The checked-in contract is an independently reviewed historical baseline, not a
cache of the current upstream pin. There is deliberately no update/generate
command. A new audit must review changes to this file and the contract together.

Only catalog-audited ordinary literal slots and spacing outside comments in
explicitly audited C++ files may change automatically. Every source comment and
its token-relative position remain exact, preserving even unfamiliar attribution
and license notices. Other literals remain exact, even in
those files (DLL names, configuration identifiers and embedded executable data).
All other non-documentation input bytes and
modes are frozen, including every other source file, build/dependency metadata,
installer, license, binary, shader, and the ImGui/font implementation. Gitlinks
and their path set are frozen before submodule checkout; the caller must still
verify initialized recursive submodules before building.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

REPOSITORY = 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git'
BRANCH = 'main'
NORMALIZER = 'cpp-structure-v1'
SOURCE_SUFFIXES = frozenset({'.c', '.cc', '.cpp', '.cxx', '.c++', '.h', '.hh', '.hpp', '.hxx', '.h++', '.inl', '.ipp', '.ixx', '.m', '.mm'})
SHA = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')
VERSION = re.compile(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')
IDENTIFIER = re.compile(r'(?:[A-Za-z_]|[^\x00-\x7f])(?:\w|[^\x00-\x7f])*')
NUMBER = re.compile(r'(?:[0-9]|\.[0-9])(?:[\w.\x80-\uffff]|\'[\w]|(?<=[eEpP])[+-])*')
PUNCTUATORS = tuple(sorted(('>>=', '<<=', '<=>', '->*', '...', '##', '::', '.*', '->', '++', '--', '<<', '>>', '<=', '>=', '==', '!=', '&&', '||', '*=', '/=', '%=', '+=', '-=', '&=', '^=', '|=', '<:', ':>', '<%', '%>', '%:', '%:%:'), key=len, reverse=True))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path(path: str) -> bool:
    if not isinstance(path, str) or not path or '\\' in path or ':' in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return False
    parts = path.split('/')
    reserved = re.compile(r'(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(?:\.|$)', re.I)
    return not path.startswith('/') and all(
        part not in ('', '.', '..') and not part.endswith((' ', '.'))
        and not reserved.match(part) and not re.search(r'[<>\"|?*]', part)
        and part.casefold() != '.git' for part in parts)


def _source(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES


def _documentation(path: str) -> bool:
    """Small allowlist: never exempt hidden inputs, legal notices or dependencies."""
    parts = PurePosixPath(path).parts
    lower = path.lower()
    legal = re.search(r'(?:license|licence|copying|copyright|notice|patents|third[-_ ]?party|eula)', lower)
    dependency = any(part.lower() in {'external', 'vendor', 'vendors', 'third_party', 'third-party', 'dependencies', 'redist'} for part in parts)
    return (PurePosixPath(path).suffix.lower() in {'.md', '.rst'} and not legal and not dependency
            and not any(part.startswith('.') for part in parts))


def _cpp_tokens(data: bytes, *, comments: list | None = None) -> tuple[list[str], list[dict]]:
    """Lex C++ structure; preserve directives, chars and token boundaries.

    This is not a C++ parser or a claim that changed strings have safe semantics.
    Strict catalog/integration/runtime gates remain required. Malformed lexical
    input fails closed. Literal encodings and user-defined suffixes stay visible.
    """
    try:
        text = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeError as exc:
        raise ValueError('unaudited-source structure: source is not UTF-8') from exc
    # Translation-phase splicing can extend a // comment or a macro. Do it before
    # lexical processing, so a backslash cannot hide active tokens from the gate.
    if '\0' in text or re.search(r'\?\?[=/(\)\'!<>-]', text):
        raise ValueError('unaudited-source structure: NUL/trigraph requires manual audit')
    original = text
    newline_positions = [i for i, value in enumerate(original) if value == '\n']
    splice_positions = [match.start() - 2 * i for i, match in enumerate(re.finditer(r'\\\n', original))]
    text = re.sub(r'\\\n', '', text)
    tokens: list[str] = []
    literals: list[dict] = []
    i = 0
    line_start = True
    directive = False
    directive_phase = -1
    macro_end = -1
    while i < len(text):
        char = text[i]
        if char in ' \t\v\f\n':
            if char == '\n':
                if directive:
                    if directive_phase == 2:
                        tokens.append('@object-macro')
                    tokens.append('@directive-end')
                line_start, directive, directive_phase = True, False, -1
            i += 1
            continue
        if text.startswith('//', i):
            end = text.find('\n', i + 2)
            end = len(text) if end < 0 else end
            if comments is not None:
                start_original = i + 2 * bisect_right(splice_positions, i)
                end_original = end + 2 * bisect_left(splice_positions, end)
                comments.append([len(tokens), original[start_original:end_original]])
            i = end
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('unaudited-source structure: unterminated comment')
            # Translation phase 3 replaces the complete comment by one space.
            # Physical newlines inside it do not end an active directive or
            # create a directive boundary after an existing code token.
            if comments is not None:
                start_original = i + 2 * bisect_right(splice_positions, i)
                end_original = end + 2 + 2 * bisect_left(splice_positions, end + 2)
                comments.append([len(tokens), original[start_original:end_original]])
            i = end + 2
            continue
        if line_start and (char == '#' or text.startswith('%:', i)):
            directive = True
            directive_phase = 0
            tokens.append('@directive-start')
        line_start = False
        if directive and directive_phase == 2:
            tokens.append('@function-macro' if char == '(' and i == macro_end else '@object-macro')
            directive_phase = -1
        literal = re.match(r'(u8|u|U|L)?(R)?(["\'])', text[i:])
        if literal:
            prefix, raw, quote = literal.groups()
            prefix = prefix or ''
            start = i
            i += literal.end()
            if raw:
                if quote != '"':
                    raise ValueError('unaudited-source structure: malformed raw literal')
                opening = text.find('(', i)
                delimiter = text[i:opening] if opening >= 0 else ''
                if opening < 0 or len(delimiter) > 16 or re.search(r'[\s()\\]', delimiter):
                    raise ValueError('unaudited-source structure: malformed raw delimiter')
                ending = ')' + delimiter + '"'
                end = text.find(ending, opening + 1)
                if end < 0:
                    raise ValueError('unaudited-source structure: unterminated raw literal')
                i = end + len(ending)
            else:
                while i < len(text):
                    if text[i] == '\n':
                        raise ValueError('unaudited-source structure: newline in literal')
                    if text[i] == '\\':
                        i += 2
                    elif text[i] == quote:
                        i += 1
                        break
                    else:
                        i += 1
                else:
                    raise ValueError('unaudited-source structure: unterminated literal')
                if i > len(text):
                    raise ValueError('unaudited-source structure: unterminated escape')
            original_offset = start + 2 * bisect_right(splice_positions, start)
            original_end = i + 2 * bisect_left(splice_positions, i)
            if directive or quote == "'":
                tokens.append(original[original_offset:original_end])
            else:
                tokens.append(prefix + ('R' if raw else '') + '"@string"')
            # Lexical user-defined suffix is significant, including adjacency.
            suffix = IDENTIFIER.match(text, i)
            if suffix:
                tokens[-1] += '@suffix:' + suffix.group()
                i = suffix.end()
            if not directive and quote == '"':
                original_end = i + 2 * bisect_left(splice_positions, i)
                literals.append({'ordinal': len(literals), 'line': bisect_right(newline_positions, original_offset) + 1,
                                 'token': original[original_offset:original_end], 'token_index': len(tokens) - 1})
            continue
        number = NUMBER.match(text, i)
        if number:
            tokens.append(number.group())
            i = number.end()
            continue
        identifier = IDENTIFIER.match(text, i)
        if identifier:
            tokens.append(identifier.group())
            if directive_phase == 0:
                directive_phase = 1 if identifier.group() == 'define' else -1
            elif directive_phase == 1:
                directive_phase, macro_end = 2, identifier.end()
            i = identifier.end()
            continue
        punctuator = next((value for value in PUNCTUATORS if text.startswith(value, i)), char)
        tokens.append(punctuator)
        i += len(punctuator)
    if directive:
        if directive_phase == 2:
            tokens.append('@object-macro')
        tokens.append('@directive-end')
    return tokens, literals


def cpp_structure_sha256(data: bytes) -> str:
    """Hash C++ tokens and exact comment provenance, excluding literal contents."""
    comments: list = []
    tokens, _ = _cpp_tokens(data, comments=comments)
    return _sha256(json.dumps([tokens, comments], ensure_ascii=True, separators=(',', ':')).encode('ascii'))


def _literal_digest(tokens: list[str], literals: list[dict], mutable_ordinals: list[int]) -> str:
    if (not isinstance(mutable_ordinals, list) or any(type(index) is not int or index < 0 or index >= len(literals) for index in mutable_ordinals)
            or mutable_ordinals != sorted(set(mutable_ordinals))):
        raise ValueError('Invalid mutable literal ordinal allowlist')
    mutable = set(mutable_ordinals)
    indexes = {literal['token_index'] for literal in literals}
    content = []
    for literal in literals:
        allowed = literal['ordinal'] in mutable
        index = literal['token_index']
        if allowed and (index - 1 in indexes or index + 1 in indexes):
            raise ValueError('Ambiguous adjacent literals cannot be mutable')
        if allowed and not re.fullmatch(r'"[^"\\%{}#\x00-\x1f\x7f]*"', literal['token']):
            raise ValueError('Mutable literal must be simple prose without format, identity or escape syntax')
        # The structure digest already preserves prefixes, suffixes and slots.
        content.append('@audited-display-literal' if allowed else literal['token'])
    return _sha256(json.dumps(content, ensure_ascii=True, separators=(',', ':')).encode('ascii'))


def cpp_literal_sha256(data: bytes, mutable_ordinals: list[int]) -> str:
    """Freeze every non-approved literal, including runtime code/configuration."""
    tokens, literals = _cpp_tokens(data)
    return _literal_digest(tokens, literals, mutable_ordinals)


def _validate_contract(contract: dict) -> None:
    required = {'schema', 'repository', 'branch', 'baseline_commit', 'normalizer', 'source_paths', 'protected_files', 'audited_sources', 'gitlinks'}
    if not isinstance(contract, dict) or set(contract) != required:
        raise ValueError('Invalid compatibility contract schema or unexpected fields')
    if type(contract['schema']) is not int or contract['schema'] != 1 or contract['normalizer'] != NORMALIZER:
        raise ValueError('Unsupported compatibility contract schema/normalizer')
    if contract['repository'] != REPOSITORY or contract['branch'] != BRANCH:
        raise ValueError('Compatibility contract repository/branch is not the fixed F5 upstream')
    if not isinstance(contract['baseline_commit'], str) or not SHA.fullmatch(contract['baseline_commit']):
        raise ValueError('Compatibility contract requires a full audited baseline SHA')
    sources = contract['source_paths']
    if not isinstance(sources, list) or not sources or not all(_path(path) and _source(path) for path in sources) or sources != sorted(set(sources)):
        raise ValueError('Invalid compatibility source path set')
    seen = set()
    for kind in ('protected_files', 'audited_sources', 'gitlinks'):
        records = contract[kind]
        if not isinstance(records, dict) or (kind != 'gitlinks' and not records):
            raise ValueError('Incomplete compatibility protected/source evidence')
        for path, record in records.items():
            if not _path(path) or path.casefold() in seen:
                raise ValueError('Unsafe or colliding compatibility path')
            seen.add(path.casefold())
            if kind == 'gitlinks':
                if not isinstance(record, str) or not SHA.fullmatch(record):
                    raise ValueError('Invalid compatibility gitlink')
                continue
            keys = {'mode', 'sha256'} | ({'structure_sha256', 'literal_sha256', 'literal_count', 'mutable_literal_ordinals'} if kind == 'audited_sources' else set())
            if not isinstance(record, dict) or set(record) != keys or record.get('mode') not in ('100644', '100755'):
                raise ValueError('Invalid compatibility file record or mode')
            if any(not isinstance(record[key], str) or not SHA256.fullmatch(record[key]) for key in keys - {'mode', 'literal_count', 'mutable_literal_ordinals'}):
                raise ValueError('Invalid compatibility SHA256 evidence')
            if kind == 'audited_sources':
                if not _source(path):
                    raise ValueError('Audited source path must be C/C++')
                count, ordinals = record['literal_count'], record['mutable_literal_ordinals']
                if type(count) is not int or count < 0 or not isinstance(ordinals, list):
                    raise ValueError('Invalid audited literal evidence')
                if any(type(index) is not int or index < 0 or index >= count for index in ordinals) or ordinals != sorted(set(ordinals)):
                    raise ValueError('Invalid audited literal ordinal allowlist')
            if kind == 'protected_files' and _documentation(path):
                raise ValueError('Documentation is incorrectly classified as protected')
    represented_sources = {path for kind in ('protected_files', 'audited_sources') for path in contract[kind] if _source(path)}
    if represented_sources != set(sources):
        raise ValueError('Incomplete compatibility source path evidence')


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key in compatibility contract')
        value[key] = item
    return value


def load_contract(path: Path | str) -> dict:
    """Load and validate reviewed evidence; never repair/regenerate mismatches."""
    contract = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    _validate_contract(contract)
    return contract


def validate_config(cfg: dict, contract: dict) -> None:
    _validate_contract(contract)
    if not isinstance(cfg, dict) or cfg.get('repository') != REPOSITORY or cfg.get('branch') != BRANCH:
        raise ValueError('upstream.json repository/branch must identify the fixed F5 upstream')
    commit = cfg.get('commit')
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError('upstream.json requires a full lowercase 40-character commit SHA; floating refs are forbidden')
    version = cfg.get('upstream_version')
    if not isinstance(version, str) or len(version) > 96 or not (VERSION.fullmatch(version) or version == 'main-' + commit[:12]):
        raise ValueError('upstream.json version must be a safe vX.Y.Z[-suffix] or main-<12sha> for this commit')


def _git(root: Path, *args: str) -> bytes:
    # No network, hooks, shell, worktree filters or replacement-object aliases.
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith('GIT_'):
            del env[key]
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0',
                'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': '', 'GIT_TERMINAL_PROMPT': '0'})
    try:
        return subprocess.check_output(['git', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', *args],
                                       cwd=root, env=env, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise ValueError('Git object verification failed: ' + ' '.join(args[:2])) from exc


def _tree(root: Path, commit: str) -> dict:
    if _git(root, 'cat-file', '-t', commit).strip() != b'commit':
        raise ValueError('Candidate SHA is not a commit object')
    result = {}
    folded = set()
    for entry in _git(root, 'ls-tree', '-r', '-z', '--full-tree', commit).split(b'\0'):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b'\t', 1)
            mode, kind, oid = metadata.decode('ascii').split()
            path = raw_path.decode('utf-8')
        except (ValueError, UnicodeError) as exc:
            raise ValueError('Unsafe candidate Git tree entry') from exc
        if not _path(path) or path.casefold() in folded:
            raise ValueError('Unsafe/case-colliding candidate Git path')
        if (mode, kind) not in {('100644', 'blob'), ('100755', 'blob'), ('160000', 'commit')}:
            raise ValueError(f'Unsupported candidate mode/symlink: {path}')
        if not SHA.fullmatch(oid):
            raise ValueError('Unsupported Git object format')
        folded.add(path.casefold())
        result[path] = {'mode': mode, 'kind': kind, 'oid': oid}
    return result


def _verify_worktree(root: Path, commit: str, tree: dict, blobs: dict[str, bytes]) -> None:
    if _git(root, 'rev-parse', '--verify', 'HEAD').decode().strip() != commit:
        raise ValueError('Pristine worktree HEAD must equal upstream.json commit')
    index = {}
    for entry in _git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode('ascii').split()
        if stage != '0':
            raise ValueError('Pristine index has unresolved stages')
        index[raw_path.decode('utf-8')] = (mode, oid)
    expected = {path: (entry['mode'], entry['oid']) for path, entry in tree.items()}
    if index != expected:
        raise ValueError('Pristine index differs from the candidate commit')
    unknown = [path.decode('utf-8') for path in _git(root, 'ls-files', '--others', '-z').split(b'\0') if path]
    # This inert marker belongs only to prepare_tree, never to upstream execution.
    if set(unknown) - {'.f5-cn-managed.json'}:
        raise ValueError('Pristine worktree has untracked/ignored inputs: ' + ', '.join(sorted(unknown)[:5]))
    if '.f5-cn-managed.json' in unknown:
        marker = root / '.f5-cn-managed.json'
        expected_owner = {'schema': 1, 'root': str(root.resolve().parent), 'repository': REPOSITORY, 'commit': commit}
        try:
            if marker.is_symlink() or not marker.is_file():
                raise ValueError('Managed marker must be a regular non-symlink file')
            owner = json.loads(marker.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
            if not isinstance(owner, dict) or type(owner.get('schema')) is not int or owner != expected_owner:
                raise ValueError('Managed marker identity must exactly match the current candidate')
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Invalid managed marker') from exc
    for relative, entry in tree.items():
        if entry['kind'] != 'blob':
            continue  # The caller validates initialized recursive submodules.
        path = root.joinpath(*relative.split('/'))
        if any(parent.is_symlink() for parent in [path, *list(path.parents)[:len(PurePosixPath(relative).parts) - 1]]):
            raise ValueError(f'Pristine worktree symlink: {relative}')
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or path.read_bytes() != blobs[relative]:
                raise ValueError(f'Pristine worktree bytes differ: {relative}')
            # Git executable mode is meaningful on POSIX; Windows cannot express it.
            if os.name != 'nt' and bool(info.st_mode & stat.S_IXUSR) != (entry['mode'] == '100755'):
                raise ValueError(f'Pristine worktree mode differs: {relative}')
        except OSError as exc:
            raise ValueError(f'Pristine worktree missing/unreadable: {relative}') from exc


def verify_source(source_root: Path | str, cfg: dict, contract: dict, *, verify_worktree: bool = True) -> dict:
    """Verify the candidate without execution/mutation; return portable evidence.

    Default additionally checks actual HEAD, index and worktree bytes. Explicit
    ``verify_worktree=False`` is ONLY a pre-checkout/pre-submodule object gate;
    callers must run the default again before upstream build/script execution.
    Neither mode initializes or verifies nested submodule worktrees.
    """
    validate_config(cfg, contract)
    root = Path(source_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Source root must be a real Git checkout directory')
    if _git(root, 'rev-parse', '--show-toplevel').decode().strip() != str(root.resolve()):
        raise ValueError('Source root is not the Git worktree root')
    if _git(root, 'remote', 'get-url', 'origin').decode().strip() != REPOSITORY:
        raise ValueError('Candidate origin is not the fixed F5 repository')
    tree = _tree(root, cfg['commit'])
    gitlinks = {path: entry['oid'] for path, entry in tree.items() if entry['kind'] == 'commit'}
    if gitlinks != contract['gitlinks']:
        raise ValueError('Protected gitlink path/revision changed; manual dependency audit required')
    source_paths = sorted(path for path, entry in tree.items() if entry['kind'] == 'blob' and _source(path))
    if source_paths != contract['source_paths']:
        raise ValueError('Unaudited source path set changed; manual integration audit required')
    audited = contract['audited_sources']
    protected = contract['protected_files']
    actual_protected = {path for path, entry in tree.items() if entry['kind'] == 'blob' and path not in audited and not _documentation(path)}
    if actual_protected != set(protected):
        added, deleted = sorted(actual_protected - set(protected)), sorted(set(protected) - actual_protected)
        raise ValueError(f'Known protected input path set changed; manual audit required (added={added[:5]}, deleted={deleted[:5]})')
    blobs = {}
    changed_sources = []
    for path, entry in tree.items():
        if entry['kind'] != 'blob':
            continue
        # Read the immutable object, not a checkout modified by localization.
        data = _git(root, 'cat-file', 'blob', entry['oid'])
        blobs[path] = data
        if path not in audited and path not in protected:
            if entry['mode'] != '100644':
                raise ValueError(f'Protected documentation executable mode changed: {path}')
            continue
        record = audited.get(path, protected.get(path))
        if entry['mode'] != record['mode']:
            raise ValueError(f'Known protected input mode changed: {path}')
        digest = _sha256(data)
        if path in protected:
            if digest != record['sha256']:
                raise ValueError(f'Known protected input bytes changed; manual audit required: {path}')
        else:
            comments: list = []
            tokens, literals = _cpp_tokens(data, comments=comments)
            structure = _sha256(json.dumps([tokens, comments], ensure_ascii=True, separators=(',', ':')).encode('ascii'))
            if structure != record['structure_sha256']:
                raise ValueError(f'Unaudited-source structure changed; manual integration audit required: {path}')
            if (len(literals) != record['literal_count'] or
                    _literal_digest(tokens, literals, record['mutable_literal_ordinals']) != record['literal_sha256']):
                raise ValueError(f'Protected non-display literal changed; manual integration audit required: {path}')
            if digest != record['sha256']:
                changed_sources.append(path)
    if verify_worktree:
        _verify_worktree(root, cfg['commit'], tree, blobs)
    return {'compatible': True, 'repository': REPOSITORY, 'branch': BRANCH, 'commit': cfg['commit'],
            'upstream_version': cfg['upstream_version'], 'baseline_commit': contract['baseline_commit'],
            'normalizer': NORMALIZER, 'protected_file_count': len(protected), 'audited_source_count': len(audited),
            'source_file_count': len(source_paths), 'gitlink_count': len(gitlinks),
            'changed_audited_sources': sorted(changed_sources), 'verified_worktree': verify_worktree,
            'recursive_submodule_worktrees_verified': False}
