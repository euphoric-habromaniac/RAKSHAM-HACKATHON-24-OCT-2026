"""Assemble the per-person handbooks (Markdown + PDF) from docs/handbook sources.

Every handbook contains the same chapters 00-09; only the role brief and the
chapter order differ. PDF = python-markdown -> one self-contained HTML ->
headless Edge/Chrome (no GPU).

Usage:
    python tools/build_handbooks.py [--only sehaj] [--no-pdf]
        [--chapters-dir DIR] [--roles-dir DIR] [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import datetime
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDBOOK = ROOT / "docs" / "handbook"
PROJECT = "Asli Awaaz"

CHAPTERS = {
    "00": "00_overview.md",
    "01": "01_service_core.md",
    "02": "02_security_privacy.md",
    "03": "03_api_ui_sim.md",
    "04": "04_ml_models.md",
    "05": "05_evaluation_results.md",
    "06": "06_hinglish_pipeline.md",
    "07": "07_tooling_ops.md",
    "08": "08_governance_promises.md",
    "09": "09_appendices.md",
}
PEOPLE = {
    "sehaj": ("Sehaj", ["04", "05", "06", "01", "00", "07", "08", "02", "03", "09"]),
    "pranjal": ("Pranjal", ["02", "01", "03", "00", "07", "08", "04", "05", "06", "09"]),
    "yash": ("Yash", ["03", "01", "02", "00", "07", "08", "04", "05", "06", "09"]),
    "kushagra": ("Kushagra", ["08", "00", "07", "03", "06", "02", "01", "04", "05", "09"]),
}
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm;
  @bottom-center { content: counter(page); font: 9pt sans-serif; color: #666; } }
html { font-family: 'Segoe UI','Nirmala UI','Mangal','Noto Sans Devanagari',Arial,sans-serif; }
body { font-size: 11pt; line-height: 1.45; color: #111; overflow-wrap: anywhere; }
h1 { font-size: 22pt; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 16pt; margin-top: 1.4em; } h3 { font-size: 13pt; } h4 { font-size: 11.5pt; }
h1,h2,h3,h4 { break-after: avoid; }
.chapter-start { break-before: page; }
.titlepage { text-align: center; padding-top: 70mm; break-after: page; }
.titlepage h1 { border: 0; font-size: 34pt; }
.titlepage p { font-size: 13pt; margin: 6px 0; }
pre, code { font-family: Consolas,'Cascadia Mono','Courier New',monospace; font-size: 8.8pt; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-all;
  background: #f5f5f5; border: 1px solid #ddd; padding: 6px 8px; break-inside: avoid; }
.codehilite { background: #f5f5f5; } .codehilite pre { margin: 0; }
code { background: #f1f1f1; padding: 0 2px; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; margin: 8px 0; font-size: 9.5pt; }
th, td { border: 1px solid #999; padding: 3px 5px; vertical-align: top;
  overflow-wrap: anywhere; word-break: break-word; }
th { background: #eee; } tr { break-inside: avoid; }
blockquote { border-left: 4px solid #bbb; margin-left: 0; padding-left: 12px; color: #444; }
img { max-width: 100%; }
a { color: #0645ad; text-decoration: none; }
"""


_WARNED: set[str] = set()


def warn(msg: str) -> None:
    if msg in _WARNED:
        return
    _WARNED.add(msg)
    print(f"WARNING: {msg}", file=sys.stderr)


def chapter_order(person: str) -> list[str]:
    return list(PEOPLE[person][1])


def read_part(path: Path, label: str) -> str:
    """Return the Markdown of a source file; a placeholder if missing/empty."""
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
        warn(f"{label}: {path} is empty")
    else:
        warn(f"{label}: {path} is missing")
    return (f"# {label}\n\n> **PLACEHOLDER** - source file `{path.name}` was "
            f"missing or empty when this handbook was built.")


def first_heading(md: str, fallback: str) -> str:
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence:
            m = re.match(r"#\s+(.+?)\s*#*\s*$", line)
            if m:
                return m.group(1)
    return fallback


def git_info(repo: Path = ROOT) -> str:
    def run(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=repo, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    try:
        branch, commit = run("rev-parse", "--abbrev-ref", "HEAD"), run("rev-parse", "--short", "HEAD")
        return f"{branch} @ {commit}" if commit else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def title_page(name: str, role_title: str, date: str, gitrev: str) -> str:
    return (f'<div class="titlepage" markdown="1">\n\n# {PROJECT} Handbook\n\n'
            f"**{name}**\n\n{role_title}\n\n{date}\n\n`{gitrev}`\n\n</div>")


def make_toc(entries: list[tuple[str, str]]) -> str:
    """entries: (anchor, label) -> Markdown bullet list linking to anchors."""
    lines = ["## Table of Contents", ""]
    lines += [f"- [{label}](#{anchor})" for anchor, label in entries]
    return "\n".join(lines)


def assemble(person: str, chapters_dir: Path, roles_dir: Path, date: str,
             gitrev: str, html_mode: bool = False) -> str:
    name = PEOPLE[person][0]
    brief = read_part(roles_dir / f"{person}.md", f"Role brief: {name}")
    parts = [("role-brief", "Role brief: ", brief)]
    for num in chapter_order(person):
        parts.append((f"ch-{num}", f"{num}. ", read_part(chapters_dir / CHAPTERS[num], f"Chapter {num}")))
    toc = make_toc([(a, lab + first_heading(t, a)) for a, lab, t in parts])
    sep = '\n\n<div class="chapter-start"></div>\n\n' if html_mode else "\n\n---\n\n"
    blocks = [title_page(name, first_heading(brief, "Role brief"), date, gitrev), toc]
    blocks += [f'<a id="{a}"></a>\n\n{t}' for a, _, t in parts]
    return sep.join(blocks) + "\n"


def md_to_html(md_text: str, title: str) -> str:
    import markdown
    body = markdown.markdown(
        md_text,
        extensions=["fenced_code", "tables", "toc", "sane_lists", "codehilite", "md_in_html"],
        extension_configs={"codehilite": {"noclasses": True, "guess_lang": False}},
    )
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")


def find_browser() -> str | None:
    return next((b for b in BROWSERS if Path(b).is_file()), None)


def html_to_pdf(html_path: Path, pdf_path: Path, browser: str | None = None) -> None:
    browser = browser or find_browser()
    if not browser:
        raise RuntimeError("No Edge/Chrome found for PDF conversion")
    profile = Path(tempfile.mkdtemp(prefix="hb_edge_"))
    pdf_path = pdf_path.resolve()
    pdf_path.unlink(missing_ok=True)
    try:
        cmd = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
               "--no-first-run", f"--user-data-dir={profile}",
               f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size < 1000:
            raise RuntimeError(f"PDF conversion failed (exit {r.returncode}): {r.stderr[-500:]}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def count_pages(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf.read_bytes()))


def build_one(person: str, chapters_dir: Path, roles_dir: Path, out_dir: Path,
              pdf: bool = True) -> dict:
    name = PEOPLE[person][0]
    date, gitrev = datetime.date.today().isoformat(), git_info()
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{name}_Handbook.md"
    md_path.write_text(assemble(person, chapters_dir, roles_dir, date, gitrev), encoding="utf-8")
    res: dict = {"md": md_path, "pdf": None}
    if pdf:
        page = md_to_html(assemble(person, chapters_dir, roles_dir, date, gitrev, True),
                          f"{PROJECT} Handbook - {name}")
        html_path = out_dir / f"{name}_Handbook.html"
        html_path.write_text(page, encoding="utf-8")
        pdf_path = out_dir / f"{name}_Handbook.pdf"
        try:
            html_to_pdf(html_path, pdf_path)
        finally:
            html_path.unlink(missing_ok=True)
        res.update(pdf=pdf_path, pages=count_pages(pdf_path))
    return res


def build_standalone(md_path: Path, pdf_path: Path) -> int:
    """Render one markdown file to a PDF (used for short briefs); returns the page count."""
    text = md_path.read_text(encoding="utf-8")
    html_path = pdf_path.with_suffix(".html")
    html_path.write_text(md_to_html(text, first_heading(text, md_path.stem)), encoding="utf-8")
    try:
        html_to_pdf(html_path, pdf_path)
    finally:
        html_path.unlink(missing_ok=True)
    return count_pages(pdf_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build per-person handbooks (MD + PDF)")
    ap.add_argument("--standalone", type=Path, help="render this markdown file to a PDF and exit")
    ap.add_argument("--pdf-out", type=Path, help="output PDF for --standalone")
    ap.add_argument("--only", choices=sorted(PEOPLE), help="build a single person")
    ap.add_argument("--chapters-dir", type=Path, default=HANDBOOK / "chapters")
    ap.add_argument("--roles-dir", type=Path, help="default: <chapters-dir>/../roles")
    ap.add_argument("--out-dir", type=Path, default=HANDBOOK / "dist")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    if a.standalone:
        pdf = a.pdf_out or a.standalone.with_suffix(".pdf")
        print(f"{a.standalone} -> {pdf} ({build_standalone(a.standalone, pdf)} pages)")
        return 0
    roles = a.roles_dir or a.chapters_dir.parent / "roles"
    rc = 0
    for person in ([a.only] if a.only else list(PEOPLE)):
        try:
            r = build_one(person, a.chapters_dir, roles, a.out_dir, not a.no_pdf)
            msg = f"{person}: {r['md']}"
            if r["pdf"]:
                msg += f" | {r['pdf']} ({r['pdf'].stat().st_size} bytes, {r['pages']} pages)"
            print(msg)
        except Exception as e:  # keep building the others
            print(f"ERROR {person}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
