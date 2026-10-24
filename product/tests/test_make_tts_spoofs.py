import json
from service.consent import get_consent
from tools import make_tts_spoofs as t

HTML = json.dumps([
    {"id": "p001_hi", "n": 1, "lang": "hindi", "topic": "Balance", "text": "मे"},
    {"id": "p002_en", "n": 2, "lang": "english", "topic": "Balance", "text": "What is my balance?"},
    {"id": "p003_hg", "n": 3, "lang": "hinglish", "topic": "Balance", "text": "Mera balance kitna hai?"},
], ensure_ascii=False)  # prompts.json contents


def test_read_prompts():
    p = t.read_prompts(HTML)
    assert ("p001_hi", "hi", "मे") in p
    assert ("p003_hg", "hg", "Mera balance kitna hai?") in p


def test_real_prompts_json_has_all_phrases():
    p = t.read_prompts(t.PROMPTS_JSON.read_text(encoding="utf-8"))
    assert len(p) == 100


def test_naming_is_ingest_compatible():
    assert t.voice_slug("Microsoft Heera Desktop - Hindi (India)") == "Microsoft-Heera-Desktop-Hindi-India"
    name = t.clip_name("Microsoft Heera", "bal_hi")
    assert name == "tts_Microsoft-Heera__bal_hi.wav"
    assert name.count("__") == 1


def test_phrases_for_culture():
    p = t.read_prompts(HTML)
    assert {x[1] for x in t.phrases_for("hi-IN", p)} == {"hi"}
    assert {x[1] for x in t.phrases_for("en-IN", p)} == {"en", "hg"}


def test_consent_passes_ingest_gate(tmp_path):
    t.write_consent("Microsoft Heera", tmp_path)
    rec = get_consent("tts_Microsoft-Heera", tmp_path)
    assert rec.signed and rec.allow_recording and rec.allow_spoof_testing
    assert "no real person" in rec.metadata["note"]
