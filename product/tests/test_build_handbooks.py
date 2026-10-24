import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_handbooks as bh  # noqa: E402


def make_dirs(tmp_path, chapters=("00", "04")):
    ch, roles = tmp_path / "chapters", tmp_path / "roles"
    ch.mkdir()
    roles.mkdir()
    for n in chapters:
        (ch / bh.CHAPTERS[n]).write_text(f"# Chapter {n} title\n\ntext {n}\n\n## Sub {n}\n", encoding="utf-8")
    (roles / "yash.md").write_text("# Yash role\n\nbrief\n", encoding="utf-8")
    return ch, roles


def test_orders_cover_all_chapters():
    for p in bh.PEOPLE:
        assert sorted(bh.chapter_order(p)) == sorted(bh.CHAPTERS)
    assert bh.chapter_order("sehaj")[:3] == ["04", "05", "06"]
    assert bh.chapter_order("pranjal")[0] == "02"
    assert bh.chapter_order("yash")[:3] == ["03", "01", "02"]


def test_assemble_order_and_toc(tmp_path):
    ch, roles = make_dirs(tmp_path)
    md = bh.assemble("yash", ch, roles, "2026-01-01", "main @ abc")
    toc = md[md.index("## Table of Contents"):md.index('<a id="role-brief"></a>')]
    assert "[00. Chapter 00 title](#ch-00)" in toc
    assert toc.count("(#ch-") == 10 and "(#role-brief)" in toc
    ids = [md.index(f'<a id="{i}"></a>') for i in ["role-brief", "ch-03", "ch-01", "ch-02", "ch-00"]]
    assert ids == sorted(ids)
    assert "## Sub 00" in md  # heading levels preserved


def test_missing_chapter_placeholder_and_warning(tmp_path, capsys):
    ch, roles = make_dirs(tmp_path)
    md = bh.assemble("yash", ch, roles, "d", "g")
    assert "PLACEHOLDER" in md
    assert "is missing" in capsys.readouterr().err


def test_first_heading_ignores_fences():
    assert bh.first_heading("```\n# no\n```\n# Yes\n", "fb") == "Yes"
    assert bh.first_heading("text", "fb") == "fb"


def test_md_to_html():
    src = "# H\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\n```\n\nहिन्दी\n"
    out = bh.md_to_html(src, "T")
    assert "<table>" in out and "<h1" in out and "हिन्दी" in out
    assert "@page" in out and 'style="' in out  # inline pygments styles
    assert "charset" in out


def test_html_mode_has_page_breaks_and_title(tmp_path):
    ch, roles = make_dirs(tmp_path)
    md = bh.assemble("yash", ch, roles, "2026-01-01", "g", html_mode=True)
    out = bh.md_to_html(md, "T")
    assert out.count('class="chapter-start"') == 12
    assert 'class="titlepage"' in out and "<h1" in out
    assert 'href="#ch-00"' in out and 'id="ch-00"' in out
