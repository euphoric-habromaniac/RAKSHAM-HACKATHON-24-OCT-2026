import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_handbook_snippets as chk  # noqa: E402

SRC = "\n".join(f"line{i}" for i in range(1, 41)) + "\n"


def run(tmp_path, chapter):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "a.py").write_text(SRC, encoding="utf-8")
    ch = tmp_path / "docs" / "handbook" / "chapters"
    ch.mkdir(parents=True)
    (tmp_path / "docs" / "handbook" / "roles").mkdir()
    (ch / "c.md").write_text(chapter, encoding="utf-8")
    report, code = chk.run(tmp_path, tmp_path / "docs" / "handbook")
    return report, code, chk.check_file(ch / "c.md", tmp_path)


def block(header, body):
    return f"{header}\n\n```python\n{body}\n```\n\n"


def statuses(results):
    return [r.status for r in results]


def test_exact_match_ok(tmp_path):
    _, code, res = run(tmp_path, block("File: `svc/a.py` (lines 3-5)", "line3\nline4  \nline5"))
    assert statuses(res) == ["ok"] and code == 0


def test_to_form_and_no_backticks(tmp_path):
    _, _, res = run(tmp_path, block("File: svc/a.py (lines 3 to 4)", "line3\nline4"))
    assert statuses(res) == ["ok"]


def test_drift_reports_source(tmp_path):
    report, code, res = run(tmp_path, block("File: `svc/a.py` (lines 3-4)", "line3\nCHANGED"))
    assert statuses(res) == ["drifted"] and code == 1
    assert "line4" in report and "CHANGED" in report


def test_missing_file(tmp_path):
    _, code, res = run(tmp_path, block("File: `nope.py` (lines 1-2)", "x"))
    assert statuses(res) == ["missing-file"] and code == 1


def test_unparsed_does_not_fail(tmp_path):
    _, code, res = run(tmp_path, block("File: `svc/a.py`", "x"))
    assert statuses(res) == ["unparsed"] and code == 0


def test_elision_in_order(tmp_path):
    ok = block("File: `svc/a.py` (lines 3-9)", "line3\n# ...\nline9")
    bad = block("File: `svc/a.py` (lines 3-9)", "line9\n# ...\nline3")
    _, _, res = run(tmp_path, ok + bad)
    assert statuses(res) == ["ok", "drifted"]


def test_approx_offset_within_slack(tmp_path):
    _, _, res = run(tmp_path, block("File: `svc/a.py` (approx. lines 10-11)", "line12\nline13"))
    assert statuses(res) == ["ok"]


def test_offset_without_tolerance_drifts(tmp_path):
    _, _, res = run(tmp_path, block("File: `svc/a.py` (lines 10-11)", "line12\nline13"))
    assert statuses(res) == ["drifted"]


def test_multi_range(tmp_path):
    _, _, res = run(tmp_path, block("File: `svc/a.py` (lines 1 to 2 and 20-21)", "line1\nline2\nline20\nline21"))
    assert statuses(res) == ["ok"]


def test_blocks_without_header_ignored(tmp_path):
    _, _, res = run(tmp_path, "text\n\n```\nfoo\n```\n")
    assert res == []
