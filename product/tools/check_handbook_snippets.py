"""Check that code snippets in the handbook match the real source files.

Each snippet is a fenced code block whose preceding non-blank line holds a
header such as ``File: `service/policy.py` (lines 25-40)``. The snippet text
is compared with the cited lines of the real file.

Usage: python tools/check_handbook_snippets.py [--repo DIR] [--handbook DIR]
Exit code 1 if any snippet is drifted or points at a missing file.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SLACK = 5
OK, DRIFTED, MISSING, UNPARSED = "ok", "drifted", "missing-file", "unparsed"
STATUSES = (OK, DRIFTED, MISSING, UNPARSED)

_PATH_RE = re.compile(r"File:\s*`?([^\s`()]+)`?")
_LINES_WORD_RE = re.compile(r"\blines?\b")
_FENCE_RE = re.compile(r"^\s*```")
_ELISION_RE = re.compile(r"\.\.\.")
_TOLERANT_WORDS = ("abridged", "trimmed", "key parts", "approx", "the parts that matter")


@dataclass
class Snippet:
    header: str
    line_no: int
    code: list[str]


@dataclass
class Result:
    snippet: Snippet
    status: str
    detail: str = ""
    actual: list[str] = field(default_factory=list)


def extract_snippets(text: str) -> list[Snippet]:
    """Return fenced blocks whose preceding non-blank line has a 'File:' header."""
    lines = text.splitlines()
    snippets: list[Snippet] = []
    i = 0
    while i < len(lines):
        if not _FENCE_RE.match(lines[i]):
            i += 1
            continue
        end = i + 1
        while end < len(lines) and not _FENCE_RE.match(lines[end]):
            end += 1
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j >= 0 and "File:" in lines[j]:
            snippets.append(Snippet(lines[j].strip(), i + 1, lines[i + 1:end]))
        i = end + 1
    return snippets


def parse_header(header: str) -> tuple[str | None, list[tuple[int, int]] | None]:
    """Return (path, ranges); ranges is [] for 'all lines', None if unparsable."""
    m = _PATH_RE.search(header)
    if not m:
        return None, None
    rest = header[m.end():]
    if "all lines" in rest:
        return m.group(1), []
    word = _LINES_WORD_RE.search(rest)
    if not word:
        return m.group(1), None
    ranges = _ranges_from(rest[word.end():])
    return m.group(1), ranges or None


def _ranges_from(body: str) -> list[tuple[int, int]]:
    """Read 'a-b and c to d, e' style ranges; skip descriptive parts."""
    ranges = []
    for part in re.split(r"\band\b|,", body):
        m = re.match(r"[\s(]*(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*\)?\s*$", part)
        if not m:
            continue
        a = int(m.group(1))
        ranges.append((a, int(m.group(2) or a)))
    return ranges


def norm(lines: list[str]) -> list[str]:
    return [ln.rstrip() for ln in lines]


def is_tolerant(snippet: Snippet, ranges: list[tuple[int, int]]) -> bool:
    low = snippet.header.lower()
    elided = any(_ELISION_RE.search(ln) for ln in snippet.code)
    return elided or len(ranges) > 1 or any(w in low for w in _TOLERANT_WORDS)


def in_order(wanted: list[str], pool: list[str]) -> str | None:
    """Return the first wanted line not found in order within pool, else None."""
    pos = 0
    for want in wanted:
        try:
            pos = pool.index(want, pos) + 1
        except ValueError:
            return want
    return None


def locate(code: list[str], source: list[str]) -> str:
    """Say where the snippet really sits in the source, if it is contiguous."""
    n = len(code)
    for start in range(len(source) - n + 1):
        if n and source[start:start + n] == code:
            return f" (snippet matches exactly at lines {start + 1}-{start + n})"
    return ""


def check_snippet(snippet: Snippet, repo: Path) -> Result:
    path, ranges = parse_header(snippet.header)
    if path is None or ranges is None:
        return Result(snippet, UNPARSED, "no parsable path/line range")
    src = repo / path
    if not src.is_file():
        return Result(snippet, MISSING, f"{path} not found")
    source = norm(src.read_text(encoding="utf-8", errors="replace").splitlines())
    code = norm(snippet.code)
    if not ranges:
        ranges = [(1, len(source))]
    exact = [ln for a, b in ranges for ln in source[a - 1:b]]
    if code == exact:
        return Result(snippet, OK)
    if not is_tolerant(snippet, ranges):
        return Result(snippet, DRIFTED, "text differs from cited lines" + locate(code, source), exact)
    lo = max(min(a for a, _ in ranges) - 1 - SLACK, 0)
    hi = max(b for _, b in ranges) + SLACK
    pool = [ln for ln in source[lo:hi] if ln.strip()]
    wanted = [ln for ln in code if ln.strip() and not _ELISION_RE.search(ln)]
    bad = in_order(wanted, pool)
    if bad is None:
        return Result(snippet, OK)
    return Result(snippet, DRIFTED, f"line not found in order: {bad.strip()!r}", source[lo:hi])


def check_file(md: Path, repo: Path) -> list[Result]:
    snippets = extract_snippets(md.read_text(encoding="utf-8"))
    return [check_snippet(s, repo) for s in snippets]


def markdown_files(handbook: Path) -> list[Path]:
    return sorted(p for sub in ("chapters", "roles") for p in (handbook / sub).glob("*.md"))


def counts(results: list[Result]) -> dict[str, int]:
    return {s: sum(r.status == s for r in results) for s in STATUSES}


def format_failure(res: Result, limit: int = 6) -> str:
    head = f"  [{res.status}] line {res.snippet.line_no}: {res.snippet.header}\n    why: {res.detail}"
    if res.status != DRIFTED:
        return head
    mine = "\n".join("      | " + ln for ln in res.snippet.code[:limit])
    real = "\n".join("      | " + ln for ln in res.actual[:limit])
    return f"{head}\n    snippet starts:\n{mine}\n    source starts:\n{real}"


def format_report(per_file: dict[str, list[Result]]) -> str:
    out = [f"{'file':32} {'ok':>4} {'drifted':>8} {'missing':>8} {'unparsed':>9}"]
    for name, results in per_file.items():
        c = counts(results)
        out.append(f"{name:32} {c[OK]:>4} {c[DRIFTED]:>8} {c[MISSING]:>8} {c[UNPARSED]:>9}")
    for name, results in per_file.items():
        bad = [r for r in results if r.status != OK]
        if bad:
            out.append(f"\n{name}")
            out.extend(format_failure(r) for r in bad)
    return "\n".join(out)


def run(repo: Path, handbook: Path) -> tuple[str, int]:
    per_file = {f"{p.parent.name}/{p.name}": check_file(p, repo) for p in markdown_files(handbook)}
    flat = [r for rs in per_file.values() for r in rs]
    c = counts(flat)
    total = "TOTAL " + " ".join(f"{k}={v}" for k, v in c.items())
    code = 1 if c[DRIFTED] or c[MISSING] else 0
    return format_report(per_file) + "\n\n" + total, code


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=root)
    ap.add_argument("--handbook", type=Path, default=None)
    args = ap.parse_args(argv)
    report, code = run(args.repo, args.handbook or args.repo / "docs" / "handbook")
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
