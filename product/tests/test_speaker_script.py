"""docs/SPEAKER_SCRIPT.txt must match tools/recorder/prompts.json (regenerate: python tools/export_speaker_script.py)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import export_speaker_script as ex  # noqa: E402
from tools.recorder import prompts as prompts_mod  # noqa: E402

TXT = ROOT / "docs" / "SPEAKER_SCRIPT.txt"
PROMPTS = ROOT / "tools" / "recorder" / "prompts.json"


def test_exporter_reads_all_100_prompts():
    prompts = ex.read_prompts()
    assert len(prompts) == 100
    assert [p["id"] for p in prompts][:3] == ["p001_hi", "p002_en", "p003_hg"]


def test_script_file_in_sync_with_prompts_json():
    raw = TXT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "SPEAKER_SCRIPT.txt must be UTF-8 with BOM"
    assert TXT.read_text(encoding="utf-8-sig") == ex.build(), "out of date: run python tools/export_speaker_script.py"
    assert ex.main(["--check"]) == 0


def test_script_lists_every_prompt_in_order():
    text = TXT.read_text(encoding="utf-8-sig")
    assert re.findall(r"^\d{3}  \[(p\d{3}_\w\w) \|", text, re.M) == [f"p{n:03d}_{('hi', 'en', 'hg')[(n - 1) % 3]}" for n in range(1, 101)]
    assert "34 Hindi, 33 English, 33 Hinglish" in text and "quiet room" in text and "normal speed" in text
    assert "\r" not in text


def test_recorder_writes_the_same_text(tmp_path):
    from tools.recorder.store import RecorderStore
    st = RecorderStore(tmp_path)
    st.write_reference_files()
    assert (tmp_path / "SPEAKER_SCRIPT.txt").read_text(encoding="utf-8-sig") == TXT.read_text(encoding="utf-8-sig")


def test_prompts_json_is_the_single_clean_source():
    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))
    assert [p["n"] for p in prompts] == list(range(1, 101))
    assert [p["id"] for p in prompts] == [f"p{n:03d}_{('hi', 'en', 'hg')[(n - 1) % 3]}" for n in range(1, 101)]
    assert all(set(p) == {"id", "n", "lang", "topic", "text"} for p in prompts)
    langs = [p["lang"] for p in prompts]
    assert (langs.count("hindi"), langs.count("english"), langs.count("hinglish")) == (34, 33, 33)
    names = {"hi": "hindi", "en": "english", "hg": "hinglish"}
    assert all(names[p["id"][-2:]] == p["lang"] for p in prompts)
    assert len({p["text"] for p in prompts}) == 100
    assert all(3 <= len(p["text"].split()) <= 20 for p in prompts)
    assert prompts_mod.load_prompts() == prompts


def test_hindi_prompts_are_devanagari_and_others_ascii():
    for p in prompts_mod.load_prompts():
        assert bool(re.search(r"[ऀ-ॿ]", p["text"])) == (p["lang"] == "hindi"), p["id"]
        if p["lang"] != "hindi":
            assert p["text"].isascii(), p["id"]


def test_prompt_phonetic_and_urgency_coverage():
    text = " ".join(p["text"] for p in prompts_mod.load_prompts()).lower()
    for w in ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "शून्य", "नौ", "jaldi", "turant", "abhi",
              "block ho jayega", "जल्दी", "तुरंत", "अभी", "ब्लॉक हो जाएगा", "haan ji", "umm", "urgent", "immediately", "right now"):
        assert w in text, w
    assert all(d in text for d in "0123456789")
    config = json.loads((ROOT / "service" / "config.json").read_text(encoding="utf-8"))["l4"]["urgency_terms"]
    assert sum(1 for t in config if t in text) >= 12
