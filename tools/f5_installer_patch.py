#!/usr/bin/env python3
"""Strict, display-only installer adapter for the pinned F5 release.

No installer is executed. All four files are preflighted before any is written.
Input accepts Git's LF/CRLF checkout conversion; emitted BAT files use UTF-8
without BOM/CRLF, PowerShell uses UTF-8 with BOM for Windows PowerShell 5.1,
and Bash uses UTF-8 without BOM/LF.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'Localization/installers.zh-CN.json'
UPSTREAM_COMMIT = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
SCRIPT_NAMES = ('setup_windows.bat', 'setup_linux.sh', 'Streamlined_fetcher_windows.bat', 'get_streamline.ps1')

# These ASCII lines execute before the first Chinese byte is interpreted by cmd.
# Original exit codes and branches remain untouched. Batch termination also ends
# the local environment scope; the console code page needs its explicit restore.
BATCH_PROLOGUE = '''REM BEGIN OPTISCALER_CN_CODEPAGE_V1
setlocal
set "_F5_CN_OLD_CP="
for /f "tokens=2 delims=:" %%C in ('chcp') do set "_F5_CN_OLD_CP=%%C"
chcp 65001 >nul
REM END OPTISCALER_CN_CODEPAGE_V1
'''
BATCH_RESTORE = 'chcp %_F5_CN_OLD_CP% >nul\n'
GENERATED_PROLOGUE = '''echo REM BEGIN OPTISCALER_CN_CODEPAGE_V1
echo set "_F5_CN_OLD_CP="
echo for /f "tokens=2 delims=:" %%%%C in ^('chcp'^) do set "_F5_CN_OLD_CP=%%%%C"
echo chcp 65001 ^>nul
echo REM END OPTISCALER_CN_CODEPAGE_V1
'''
GENERATED_RESTORE = 'echo chcp %%_F5_CN_OLD_CP%% ^>nul\n'
PAUSE_TEXT = '按任意键继续 . . .'


def _conflict(message: str) -> RuntimeError:
    return RuntimeError('integration conflict: F5 installer ' + message)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _parts(line: str, name: str) -> tuple[str, str, str]:
    """Split only explicit display sites; do not translate arbitrary literals."""
    # Both stand-alone PowerShell and the fetcher's inline PowerShell diagnostics.
    match = re.search(r'''\b(?:throw|Write-Host|Write-Error)\s+\(?(['"])((?:`.|(?!\1).)*)\1''', line)
    if match:
        return line[:match.start(2)], match.group(2), line[match.end(2):]
    if name.endswith('.sh'):
        match = re.match(r'^\s*(?:echo|read(?:\s+-[a-z]+)*)\s+"((?:\\.|[^"\\])*)"', line)
        if match:
            return line[:match.start(1)], match.group(1), line[match.end(1):]
    if name.endswith('.bat'):
        match = re.search(r'\bset /p (?:"[A-Za-z_]\w*=|[A-Za-z_]\w*=")(.*)"$', line)
        if match:
            return line[:match.start(1)], match.group(1), line[match.end(1):]
        matches = list(re.finditer(r'\becho[ \t]+', line))
        if matches:
            end = matches[-1].end()
            return line[:end], line[end:], ''
        match = re.search(r'\bchoice .* /m "(.*)"$', line)
        if match:
            return line[:match.start(1)], match.group(1), line[match.end(1):]
    raise _conflict(f'{name}: unsupported display anchor: {line!r}')


def _variables(text: str) -> tuple[str, ...]:
    # Full PowerShell subexpressions here contain no nested parenthesis in this
    # pinned release. Preserve them verbatim rather than translating identifiers.
    return tuple(re.findall(r'\$\([^\n]*?\)|\$\{[^}]+\}|\$[A-Za-z_]\w*(?:\.\w+)*|\$[0-9@#?]|'
                            r'%+[A-Za-z_]\w*%+|%+[A-Za-z]|![A-Za-z_]\w*!', text))


def _validate_entry(entry: dict, name: str) -> None:
    if any(c in entry['source'] + entry['translation'] for c in '\r\n\0'):
        raise _conflict(f'{name}:{entry["line"]}: multiline or NUL display text')
    old = _parts(entry['source'], name)
    new = _parts(entry['translation'], name)
    if old[0] != new[0] or old[2] != new[2] or _variables(old[1]) != _variables(new[1]):
        raise _conflict(f'{name}:{entry["line"]}: display boundary or variable changed')
    if not re.search('[\u4e00-\u9fff]', new[1]):
        raise _conflict(f'{name}:{entry["line"]}: Chinese display text missing')
    # Preserve every shell expansion/escaping and batch metacharacter. PowerShell
    # and Bash prose is inside quoted literals; their delimiters are checked above.
    if name.endswith('.bat') and not re.search(r'\bWrite-(?:Host|Error)\b', entry['source']):
        if re.findall(r'[\^&|<>()"%!]', old[1]) != re.findall(r'[\^&|<>()"%!]', new[1]):
            raise _conflict(f'{name}:{entry["line"]}: batch escaping changed')
    if name.endswith('.sh'):
        if re.findall(r'\\.|`', old[1]) != re.findall(r'\\.|`', new[1]):
            raise _conflict(f'{name}:{entry["line"]}: shell escaping changed')


def _encoding_support(text: str, name: str) -> str:
    if not name.endswith('.bat'):
        return text
    if text.count('@echo off\n') != (2 if name == 'setup_windows.bat' else 1):
        raise _conflict(f'{name}: batch startup changed')
    text = text.replace('@echo off\n', '@echo off\n' + BATCH_PROLOGUE, 1)
    text = re.sub(r'^(exit /b [01])$', lambda m: BATCH_RESTORE + m.group(1), text, flags=re.M)
    text = re.sub(r'^([ \t]*)pause$', lambda m: m.group(1) + 'echo ' + PAUSE_TEXT + '\n' + m.group(1) + 'pause >nul', text, flags=re.M)
    if name == 'setup_windows.bat':
        start = 'echo setlocal EnableDelayedExpansion\n'
        if text.count(start) != 1 or text.count('echo pause\n') != 1:
            raise _conflict(f'{name}: generated uninstaller changed')
        text = text.replace(start, start + GENERATED_PROLOGUE)
        # Restore before the original final self-deletion block: attempting to
        # restore after the generated script deletes itself is not reliable.
        text = text.replace('echo pause\n', 'echo echo ' + PAUSE_TEXT + '\necho pause ^>nul\n' + GENERATED_RESTORE)
    return text


def _render(text: str, record: dict) -> str:
    name = record['path']
    lines = text.splitlines(keepends=True)
    seen: set[int] = set()
    for entry in record['entries']:
        index = entry['line'] - 1
        if index in seen or index < 0 or index >= len(lines) or lines[index] != entry['source'] + '\n':
            raise _conflict(f'{name}:{entry["line"]}: source anchor changed')
        seen.add(index)
        _validate_entry(entry, name)
        lines[index] = entry['translation'] + '\n'
    return _encoding_support(''.join(lines), name)


def _encode(text: str, name: str) -> bytes:
    if name.endswith('.bat'):
        return text.replace('\n', '\r\n').encode('utf-8')
    return text.encode('utf-8-sig' if name.endswith('.ps1') else 'utf-8')


def patch_installer_scripts(source: Path | str) -> None:
    """Localize all pinned entrypoints in ``source``; reject drift before writes.

    Reapplying to exact generated files is a no-op. A partially or manually
    changed output is rejected, including translations and executable code.
    """
    source = Path(source)
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    if catalog.get('upstream_commit') != UPSTREAM_COMMIT or tuple(r['path'] for r in catalog['scripts']) != SCRIPT_NAMES:
        raise _conflict('catalog contract changed')
    pending: list[tuple[Path, bytes]] = []
    for record in catalog['scripts']:
        name = record['path']
        path = source / name
        try:
            data = path.read_bytes()
            text = data.decode('utf-8-sig').replace('\r\n', '\n')
        except (OSError, UnicodeError) as exc:
            raise _conflict(f'{name}: missing or invalid UTF-8 source') from exc
        actual = _digest(text)
        if actual == record['localized_sha256']:
            output = text
        elif actual == record['source_sha256']:
            output = _render(text, record)
            if _digest(output) != record['localized_sha256']:
                raise _conflict(f'{name}: generated output fingerprint changed')
        else:
            raise _conflict(f'{name}: source drift or modified/partial localization; expected pinned {UPSTREAM_COMMIT}')
        encoded = _encode(output, name)
        if encoded != data:
            pending.append((path, encoded))
    for path, data in pending:
        path.write_bytes(data)
