import csv
import json
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest

from eval import collect_results as cr
from eval import fill_placeholders as fp


def make_wav(path, seconds=1.0, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))


@pytest.fixture
def rec(tmp_path):
    d = tmp_path / "rec"
    d.mkdir()
    rows = []
    for spk in ("a", "b"):
        for i in range(3):
            make_wav(d / f"{spk}{i}.wav", 2.0)
            rows.append((f"{spk}{i}.wav", spk, "yes"))
    make_wav(d / "nc.wav")
    rows.append(("nc.wav", "c", "no"))
    rows.append(("ghost.wav", "c", "yes"))
    m = tmp_path / "m.csv"
    with open(m, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "speaker_id", "consent"])
        w.writerows(rows)
    return d, m


def test_counts_only_consented_existing(rec):
    d, m = rec
    r = cr.collect_recordings(d, m)
    assert (r["n_speakers"], r["n_clips"], r["n_rejected"]) == (2, 6, 2)
    assert r["clips_per_speaker"]["uniform"]
    assert r["total_minutes"] == pytest.approx(0.2)


def test_bad_manifest_columns(tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("file,speaker\nx,y\n")
    with pytest.raises(SystemExit):
        cr.collect_recordings(tmp_path, m)


def test_baseline_and_cli(rec, tmp_path):
    d, m = rec
    res = tmp_path / "results"
    res.mkdir()
    with open(res / "clean16k.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utt_id", "label", "score"])
        for i, (lab, s) in enumerate([("bonafide", 2), ("bonafide", 3), ("spoof", -1), ("spoof", 0)]):
            w.writerow([i, lab, s])
    out = tmp_path / "results.json"
    cr.main(["--recordings", str(d), "--manifest", str(m), "--baseline-results", str(res), "--out", str(out)])
    j = json.loads(out.read_text())
    assert j["baseline_eer"]["clean16k"]["eer_percent"] == 0.0
    assert j["provenance"]["command"] and j["provenance"]["generated_at"]
    assert j["hinglish_set"]["manifest"]["sha256"]


def test_needs_an_input():
    with pytest.raises(SystemExit):
        cr.build(None, None, None, "x")


SLIDES = {
    "evidence.html": 'x <b style="a">[N]</b> speakers <b>[M]</b> clips under <b>[x]</b>% note [N] [x]',
    "trust.html": 'gap <b style="b">[x]</b> points',
    "arch2.html": '<b>[Bank retention policy]</b>',
    "other.html": "<b>[Name: x]</b>",
}

RESULTS = {"provenance": {"generated_at": "t", "command": "c"},
           "hinglish_set": {"n_speakers": 12, "n_clips": 60,
                            "clips_per_speaker": {"min": 5, "max": 5, "uniform": True},
                            "manifest": {"file": "m.csv"}}}


@pytest.fixture
def slides(tmp_path):
    s = tmp_path / "deck" / "slides"
    s.mkdir(parents=True)
    for k, v in SLIDES.items():
        (s / k).write_text(v, encoding="utf-8")
    return s


def test_nothing_sourced_leaves_all(slides, tmp_path):
    out = tmp_path / "o" / "slides"
    rep = fp.fill(slides, out, {}, {})
    assert all(r[3] == "open" for r in rep)
    for k, v in SLIDES.items():
        assert (out / k).read_text() == v


def test_fills_only_sourced_and_keeps_originals(slides, tmp_path):
    out = tmp_path / "o" / "slides"
    targets = {"genuine_stepup_target_pct": {"value": 7, "decided_by": "team"},
               "fairness_gap_points": {"value": 3, "decided_by": ""},
               "bank_retention_policy": {"value": "90 days <b>", "decided_by": "bank"}}
    rep = {r[2]: r[3] for r in fp.fill(slides, out, RESULTS, targets)}
    assert rep["fairness_gap_points"] == "open"
    ev = (out / "evidence.html").read_text()
    assert "12</b>" not in ev and "12 speakers" in ev and "5 clips under 7%" in ev
    assert "note [N] [x]" in ev
    assert (out / "trust.html").read_text() == SLIDES["trust.html"]
    assert "90 days &lt;b&gt;" in (out / "arch2.html").read_text()
    assert (out / "other.html").read_text() == SLIDES["other.html"]
    assert (slides / "evidence.html").read_text() == SLIDES["evidence.html"]


def test_unequal_clips_need_rule_and_bad_values():
    res = json.loads(json.dumps(RESULTS))
    res["hinglish_set"]["clips_per_speaker"] = {"min": 3, "max": 6, "uniform": False}
    v = fp.resolve(res, {})
    assert v["hinglish_m"][0] is None and v["hinglish_n"][0] == "12"
    v = fp.resolve(res, {"hinglish_m_rule": {"value": "min", "decided_by": "t"},
                         "genuine_stepup_target_pct": {"value": 150, "decided_by": "t"},
                         "fairness_gap_points": {"value": True, "decided_by": "t"}})
    assert v["hinglish_m"][0] == "3"
    assert v["genuine_stepup_target_pct"][0] is None and v["fairness_gap_points"][0] is None


def test_refuses_to_overwrite_source(slides):
    with pytest.raises(SystemExit):
        fp.fill(slides, slides, {}, {})
