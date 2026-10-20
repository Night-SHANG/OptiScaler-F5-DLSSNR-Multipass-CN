#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import re

from loclib import (
    Candidate,
    _string_literals_in_region,
    extract_string_expression,
    find_candidates,
    find_matching,
    mask_cpp,
    should_exclude,
    split_args,
)


def _scoped(rel: str, spec: dict) -> bool:
    return fnmatch.fnmatch(rel, spec.get("glob", ""))


def _call_matches(text: str, name: str):
    masked = mask_cpp(text)
    if name.startswith("."):
        pattern = re.compile(re.escape(name) + r"\s*\(")
    else:
        pattern = re.compile(r"(?<![\w:])" + re.escape(name) + r"\s*\(")
    for match in pattern.finditer(masked):
        p = masked.find("(", match.start(), match.end() + 2)
        if p < 0:
            continue
        q = find_matching(text, p)
        if q < 0:
            continue
        yield masked, p, q, split_args(text, p + 1, q)


def find_scoped_literal_call_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Scan every literal inside selected UI call arguments.

    This covers UI builders where the visible text is assembled at runtime, for
    example PipelineUi::add(..., "HDR / exposure / " + value + "%").
    Rules are deliberately glob-scoped so generic helper names such as ``add``
    cannot turn unrelated engine strings into localization candidates.
    """
    out: list[Candidate] = []
    for spec in rules.get("scoped_literal_calls", []):
        if not _scoped(rel, spec):
            continue
        for name, first_index in spec.get("calls", {}).items():
            for _masked, _p, _q, args in _call_matches(text, name):
                for arg_index, (a, b) in enumerate(args):
                    if arg_index < int(first_index):
                        continue
                    for left, right, source, expr in _string_literals_in_region(text, a, b):
                        if should_exclude(source, rules):
                            continue
                        out.append(
                            Candidate(
                                rel,
                                f"{name}:scoped-literal",
                                arg_index,
                                source,
                                left,
                                right,
                                text.count("\n", 0, left) + 1,
                                expr,
                                True,
                            )
                        )
    return out


def find_return_literal_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Catalog literals returned by small UI text helper functions."""
    masked = mask_cpp(text)
    out: list[Candidate] = []
    for spec in rules.get("return_literal_functions", []):
        if not _scoped(rel, spec):
            continue
        for name in spec.get("functions", []):
            pattern = re.compile(r"\b" + re.escape(name) + r"\s*\(")
            for match in pattern.finditer(masked):
                p = masked.find("(", match.start(), match.end() + 2)
                if p < 0:
                    continue
                q = find_matching(text, p)
                if q < 0:
                    continue
                brace = masked.find("{", q + 1)
                if brace < 0:
                    continue
                close = find_matching(text, brace, "{", "}")
                if close < 0:
                    continue
                for ret in re.finditer(r"\breturn\b", masked[brace + 1 : close]):
                    start = brace + 1 + ret.end()
                    semi = masked.find(";", start, close)
                    if semi < 0:
                        continue
                    expr = text[start:semi]
                    source = extract_string_expression(expr.strip())
                    if source is None or should_exclude(source, rules):
                        continue
                    left = start + (len(expr) - len(expr.lstrip()))
                    right = semi - (len(expr) - len(expr.rstrip()))
                    out.append(
                        Candidate(
                            rel,
                            f"return:{name}",
                            0,
                            source,
                            left,
                            right,
                            text.count("\n", 0, left) + 1,
                            text[left:right],
                            True,
                        )
                    )
    return out


def find_assignment_literal_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Scan literals inside explicitly named UI text variable assignments."""
    masked = mask_cpp(text)
    out: list[Candidate] = []
    for spec in rules.get("literal_assignments", []):
        if not _scoped(rel, spec):
            continue
        for name in spec.get("names", []):
            pattern = re.compile(r"\b" + re.escape(name) + r"\s*=")
            for match in pattern.finditer(masked):
                eq = masked.find("=", match.start(), match.end() + 1)
                semi = masked.find(";", eq + 1) if eq >= 0 else -1
                if eq < 0 or semi < 0:
                    continue
                for left, right, source, expr in _string_literals_in_region(text, eq + 1, semi):
                    if should_exclude(source, rules):
                        continue
                    out.append(
                        Candidate(
                            rel,
                            f"assignment:{name}",
                            0,
                            source,
                            left,
                            right,
                            text.count("\n", 0, left) + 1,
                            expr,
                            True,
                        )
                    )
    return out


def find_ui_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Return every known user-visible UI candidate for one source file.

    ``loclib.find_candidates`` remains the generic scanner.  This layer adds
    narrowly-scoped data-flow cases used by the newer DLSS-NR UI without
    broadening generic helper names across the rendering codebase.
    """
    from f5_scan import find_f5_candidates
    results = list(find_candidates(text, rel, rules))
    results.extend(find_f5_candidates(text, rel, rules))
    results.extend(find_scoped_literal_call_candidates(text, rel, rules))
    results.extend(find_return_literal_candidates(text, rel, rules))
    results.extend(find_assignment_literal_candidates(text, rel, rules))

    uniq: dict[tuple[int, int], Candidate] = {}
    for candidate in results:
        key = (candidate.start, candidate.end)
        current = uniq.get(key)
        if current is None or candidate.rewrite:
            uniq[key] = candidate
    return sorted(uniq.values(), key=lambda candidate: candidate.start)
