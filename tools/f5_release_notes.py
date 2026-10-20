#!/usr/bin/env python3
"""Compute static catalog progress and update only its marked release section.

No network or credentials are used. Callers decide whether missing/stale entries
are acceptable for publication; they never contribute to effective coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN"
BEGIN_MARKER = "<!-- f5-cn-static-catalog-progress:begin -->"
END_MARKER = "<!-- f5-cn-static-catalog-progress:end -->"
STATES = ("reviewed", "machine_translated")
SCAN_KINDS = ("added", "changed", "removed")


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _commit(value, name="cn_commit"):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"{name} must be a full 40-character lowercase commit SHA")
    return value


def summarize(catalog: dict, zh: dict, retained: dict, pending: dict) -> dict:
    """Summarize active entries, without mutating or upgrading source provenance.

    A valid but different zh-CN source hash is stale; a corrupt catalog hash or
    malformed translation hash is rejected. ``newly_effective`` means the union
    of scan.added/changed keys that are active and effective *now*, not a claim
    that they were untranslated previously. Raw scan arrays can contain repeated,
    obsolete, or no-longer-known keys and are reported independently.
    """
    for name, value in (("catalog", catalog), ("zh", zh), ("retained", retained),
                        ("pending", pending)):
        _object(value, name)
    if catalog.get("channel") != "master":
        raise ValueError("catalog channel must be master")
    if zh.get("locale") != "zh-CN" or pending.get("locale") != "zh-CN":
        raise ValueError("zh and pending locale must be zh-CN")
    upstream = _commit(catalog.get("upstream_commit"), "catalog upstream_commit")
    if retained.get("upstream_commit") != upstream:
        raise ValueError("retained upstream_commit does not match catalog")
    entries = _object(catalog.get("entries"), "catalog entries")
    translations = _object(zh.get("entries"), "zh entries")
    active = {}
    for key, entry in entries.items():
        _object(entry, f"catalog {key}")
        if not isinstance(key, str) or not key:
            raise ValueError("catalog entry key must be a nonempty string")
        if not isinstance(entry.get("obsolete", False), bool):
            raise ValueError(f"{key}: obsolete must be a boolean")
        if entry.get("obsolete"):
            continue
        source = entry.get("source")
        if not isinstance(source, str):
            raise ValueError(f"{key}: catalog source must be a string")
        expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if entry.get("source_hash") != expected_hash:
            raise ValueError(f"{key}: catalog source_hash mismatch")
        active[key] = entry

    records = retained.get("entries")
    if not isinstance(records, list):
        raise ValueError("retained entries must be an array")
    retained_keys = set()
    for record in records:
        _object(record, "retained entry")
        key = record.get("key")
        if not isinstance(key, str) or key not in active or key in retained_keys:
            raise ValueError(f"retained key is inactive, unknown, or duplicate: {key!r}")
        if record.get("source") != active[key]["source"]:
            raise ValueError(f"{key}: retained source mismatch")
        if not isinstance(record.get("reason"), str) or not record["reason"].strip():
            raise ValueError(f"{key}: retained reason is required")
        retained_keys.add(key)

    counts = {"reviewed": 0, "machine_translated": 0, "missing": 0, "stale": 0,
              "changed_display_translations": 0, "retained_technical_entries": 0}
    effective_keys = set()
    for key, entry in active.items():
        translation = translations.get(key)
        if translation is None:
            if key in retained_keys:
                raise ValueError(f"{key}: retained translation is missing")
            counts["missing"] += 1
            continue
        _object(translation, f"zh {key}")
        state = translation.get("state")
        if state not in STATES:
            raise ValueError(f"{key}: unknown translation state {state!r}")
        source_hash = translation.get("source_hash")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError(f"{key}: malformed zh source_hash")
        text = translation.get("text")
        if not isinstance(text, str):
            raise ValueError(f"{key}: translation text must be a string")
        if key in retained_keys and (text != entry["source"] or source_hash != entry["source_hash"]):
            raise ValueError(f"{key}: retained translation is changed, missing, or stale")
        if not text:
            counts["missing"] += 1
            continue
        if source_hash != entry["source_hash"]:
            counts["stale"] += 1
            continue
        if text == entry["source"] and key not in retained_keys:
            raise ValueError(f"{key}: unchanged translation is not declared retained")
        counts[state] += 1
        counts["retained_technical_entries" if key in retained_keys
               else "changed_display_translations"] += 1
        effective_keys.add(key)

    scan = _object(pending.get("scan"), "pending scan")
    raw_counts, unique_counts, active_counts, key_sets = {}, {}, {}, {}
    for kind in SCAN_KINDS:
        values = scan.get(kind)
        if not isinstance(values, list) or any(not isinstance(key, str) or not key for key in values):
            raise ValueError(f"pending scan.{kind} must be an array of nonempty string keys")
        key_sets[kind] = set(values)
        raw_counts[kind] = len(values)
        unique_counts[kind] = len(key_sets[kind])
        active_counts[kind] = len(key_sets[kind] & active.keys())
    return {
        "upstream_commit": upstream, "total": len(active), **counts,
        "effective": len(effective_keys),
        "coverage": 100.0 * len(effective_keys) / len(active) if active else None,
        "scan_raw": raw_counts, "scan_unique": unique_counts,
        "scan_active_unique": active_counts,
        "scan_removed_obsolete_unique": sum(
            key in entries and entries[key].get("obsolete", False) for key in key_sets["removed"]),
        "newly_effective": len((key_sets["added"] | key_sets["changed"]) & effective_keys),
    }


def render_section(stats: dict, cn_commit: str) -> str:
    """Render a marked Chinese section, with evidence pinned to the supplied SHA."""
    _commit(cn_commit)
    upstream = _commit(stats["upstream_commit"], "stats upstream_commit")
    base = f"https://github.com/{REPOSITORY}"
    coverage = f'{stats["coverage"]:.2f}%' if stats["coverage"] is not None else "无活动条目"
    raw, unique, active = (stats[key] for key in ("scan_raw", "scan_unique", "scan_active_unique"))
    return "\n".join([
        BEGIN_MARKER,
        "## 汉化进度：静态词库覆盖",
        "",
        f'- 统计对应中文发布提交：[`{cn_commit}`]({base}/commit/{cn_commit})；'
        f'上游源文提交：`{upstream}`。',
        f'- 当前活动条目 {stats["total"]}：已变更中文显示值 {stats["changed_display_translations"]}，'
        f'有意原样保留技术项 {stats["retained_technical_entries"]}；'
        f'缺失 {stats["missing"]}，过期 {stats["stale"]}。'
        f'有效静态词库覆盖 {stats["effective"]}/{stats["total"]}（{coverage}）。',
        f'- 有效条目沿用的状态：`reviewed` {stats["reviewed"]}，'
        f'`machine_translated` {stats["machine_translated"]}。'
        'AI 翻译、AI 审校及其复用项仍保留机器状态，不冒充本次人工审核。',
        f'- 本次 `pending.scan` 原始记录：新增 {raw["added"]}、变更 {raw["changed"]}、'
        f'移除 {raw["removed"]}；各自去重键数 {unique["added"]}/{unique["changed"]}/{unique["removed"]}。'
        f'其中当前活动去重键数 {active["added"]}/{active["changed"]}/{active["removed"]}；'
        f'移除记录中已废弃的去重键数 {stats["scan_removed_obsolete_unique"]}。',
        f'- 新增或变更集合中当前有效的去重条目 {stats["newly_effective"]}'
        '（新增与变更取并集，缺失/过期不计入；不代表与前一版相比新增了同等数量的译文）。',
        f'- 证据：[覆盖与验收清单]({base}/blob/{cn_commit}/COVERAGE.md)、'
        f'[报告目录]({base}/tree/{cn_commit}/reports)、'
        f'[技术项保留理由]({base}/blob/{cn_commit}/Localization/retained-English.json)。'
        '本节数字从该提交词库实时计算，不沿用报告中的历史计数。',
        "",
        '以上是静态候选词库覆盖，不是所有运行时 UI 的穷举覆盖。'
        '未执行实际 GPU/游戏/视觉验收；构建与静态检查不能代替游戏渲染、性能、中文排版、'
        '裁切、字体和缩放验收，未知外部诊断仍可能显示英文。',
        END_MARKER,
    ])


def _marker_span(text: str):
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count == end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise ValueError("duplicate or unpaired progress marker")
    begin, end = text.index(BEGIN_MARKER), text.index(END_MARKER)
    if end < begin:
        raise ValueError("reversed progress markers")
    return begin, end + len(END_MARKER)


def update_body(body: str, section: str) -> str:
    """Append/replace exactly one marked block; preserve every outside character."""
    if not isinstance(body, str) or not isinstance(section, str):
        raise ValueError("body and section must be strings")
    if _marker_span(section) != (0, len(section)):
        raise ValueError("section must contain exactly one complete marked block")
    span = _marker_span(body)
    if span is None:
        return body + ("\n\n" if body else "") + section
    begin, end = span
    return body[:begin] + section + body[end:]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cn-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _commit(args.cn_commit)
        inputs = ("Localization/master/catalog.json", "Localization/zh-CN.json",
                  "Localization/retained-English.json", "Localization/master/pending.json")
        documents = []
        for path in inputs:
            try:
                result = subprocess.run(
                    ["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(args.repo_root),
                     "show", f"{args.cn_commit}:{path}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Cannot read cn_commit inputs") from exc
            if result.returncode:
                raise ValueError(f"Cannot read cn_commit input: {path}")
            documents.append(json.loads(result.stdout.decode("utf-8-sig")))
        stats = summarize(*documents)
        output = render_section(stats, args.cn_commit)
        if args.body_file is not None:
            # read_text's universal newline handling would alter unrelated CRLF bytes.
            output = update_body(args.body_file.read_bytes().decode("utf-8"), output)
        args.output.write_bytes(output.encode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
