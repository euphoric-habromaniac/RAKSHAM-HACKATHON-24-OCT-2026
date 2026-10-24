import csv
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import verify_consent as vc  # noqa: E402
from service.consent import ConsentRecord, save_consent  # noqa: E402


def write_wav(path, sr=16000, seconds=2.0):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32"), sr, subtype="PCM_16")


def make_session(tmp_path, speaker="spk01", signed=True, sr=16000, wav=True, rows=1, **consent_kw):
    audio, consent = tmp_path / "audio", tmp_path / "consent"
    audio.mkdir(exist_ok=True)
    if signed is not None:
        save_consent(ConsentRecord(speaker_id=speaker, full_name="T", signed=signed, **consent_kw), consent)
    manifest = tmp_path / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(vc.REQUIRED_COLUMNS)
        for i in range(rows):
            name = f"{speaker}__p{i}.wav"
            w.writerow([speaker, f"p{i}", "english", "Hindi-belt", "25-34", "", "laptop", "2.00", name])
            if wav:
                write_wav(audio / name, sr=sr)
    return manifest, consent, audio


def run(manifest, consent, audio, *extra):
    argv = ["--manifest", str(manifest), "--consent-dir", str(consent), "--audio-dir", str(audio), *extra]
    return vc.main(argv)


def test_pass(tmp_path, capsys):
    assert run(*make_session(tmp_path, rows=3)) == 0
    assert "PASS: 3/3" in capsys.readouterr().out


def test_missing_consent_fails(tmp_path, capsys):
    assert run(*make_session(tmp_path, signed=None)) == 1
    assert "no consent record" in capsys.readouterr().out


def test_unsigned_fails(tmp_path, capsys):
    assert run(*make_session(tmp_path, signed=False)) == 1
    assert "not signed" in capsys.readouterr().out


def test_wrong_sample_rate_fails(tmp_path, capsys):
    assert run(*make_session(tmp_path, sr=44100)) == 1
    assert "sample rate 44100" in capsys.readouterr().out


def test_missing_file_fails(tmp_path, capsys):
    assert run(*make_session(tmp_path, wav=False)) == 1
    assert "file missing" in capsys.readouterr().out


def test_duplicate_row_fails(tmp_path, capsys):
    manifest, consent, audio = make_session(tmp_path)
    lines = manifest.read_text(encoding="utf-8").splitlines(True)
    manifest.write_text("".join(lines + [lines[1]]), encoding="utf-8")
    assert run(manifest, consent, audio) == 1
    assert "duplicate row" in capsys.readouterr().out


def test_non_wav_drop_fails_with_ingest_hint(tmp_path, capsys):
    manifest, consent, audio = make_session(tmp_path, wav=False)
    (audio / "spk01__p0.wav").unlink(missing_ok=True)
    text = manifest.read_text(encoding="utf-8").replace("spk01__p0.wav", "spk01__p0.webm")
    manifest.write_text(text, encoding="utf-8")
    (audio / "spk01__p0.webm").write_bytes(b"not really webm")
    assert run(manifest, consent, audio) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "run ingest to convert" in out


def test_wrong_rate_wav_stays_strict(tmp_path, capsys):
    assert run(*make_session(tmp_path, sr=44100)) == 1
    assert "run ingest to convert" in capsys.readouterr().out


def test_optional_consents_required_on_flag(tmp_path, capsys):
    args = make_session(tmp_path, allow_spoof_testing=False, allow_voice_cloning=False)
    assert run(*args) == 0
    assert run(*args, "--allow-spoof-testing") == 1
    assert run(*args, "--allow-cloning") == 1
    assert "voice cloning not allowed" in capsys.readouterr().out


# ---- static checks on the recorder page (tools/recorder/static) ----
STATIC = ROOT / "tools" / "recorder" / "static"


class _Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "input":
            self.inputs.append((d, [k for k, _ in attrs]))


@pytest.fixture(scope="module")
def page():
    return {n: (STATIC / n).read_text(encoding="utf-8") for n in ("index.html", "app.js", "style.css")}


def test_consent_inputs_not_preticked_or_prefilled(page):
    p = _Inputs()
    p.feed(page["index.html"])
    consent = [names for d, names in p.inputs if d.get("id", "").startswith("c-")]
    assert len(consent) == 3 and all("checked" not in names for names in consent)
    assert all("value" not in d for d, _ in p.inputs if d.get("id") == "full-name")
    need = {"full-name", "age-band", "gender", "accent-group", "device", "language", "c-rec", "c-spoof", "c-clone", "speaker-list"}
    assert need <= p.ids
    assert "speaker-id" not in p.ids  # ids are generated, never typed


def test_required_ui_strings(page):
    both = page["index.html"] + page["app.js"]
    for s in ("Continue a speaker", "New speaker", "Speaker profile", "SAVING TO DISK", "NOT SAVING", "Download zip", "Download zip (all speakers)",
              "Finish &amp; download zip", "Resuming: ", "saved to disk", "Go to sentence", "Switch speaker", "Redo", "beforeunload",
              "/api/zip", "/api/clip", "/api/profile", "/api/speakers", "/api/prompts"):
        assert s in both, s


def test_no_browser_storage_folder_picker_or_external_urls(page):
    for name, text in page.items():
        low = text.lower()
        for s in ("localstorage", "sessionstorage", "indexeddb", "showdirectorypicker", "navigator.storage", "http://", "https://", "cdn"):
            assert s not in low, (name, s)
    assert 'src="//' not in page["index.html"].lower()


def test_page_only_talks_to_its_own_server(page):
    import re
    calls = re.findall(r"""(?:fetch\(|apiJson\()\s*([`'"])(.*?)\1""", page["app.js"])
    assert calls and all(c[1].startswith("/api/") for c in calls)
    assert re.findall(r"""(?:src|href)="([^"#]*)\"""", page["index.html"]) == ["/style.css", "/api/zip", "/app.js"]


def test_old_recorder_page_is_gone():
    assert not (ROOT / "tools" / ("record" + ".html")).exists()


def test_app_js_has_no_giant_functions(page):
    import re
    starts = [m.start() for m in re.finditer(r"^(?:async )?function \w+", page["app.js"], re.M)]
    lens = [b - a for a, b in zip(starts, starts[1:] + [len(page["app.js"])])]
    assert max(lens) < 3000


# ---- recorder layout: <Speaker>/N.wav + profile.json + consent.json ----
def make_recorder_dir(tmp_path, numbers=(1, 2, 3), signed=True, allow_spoof=True, sid="k7f3q9xa", clip_sr=16000):
    from tools.recorder.store import RecorderStore
    root = tmp_path / "recordings_awaaz"
    st = RecorderStore(root)
    st.save_profile({"name": "Test Person", "age_band": "25-34", "gender": "", "accent_group": "Hindi-belt", "device": "laptop",
                     "consent_language": "en", "allow_recording": True, "allow_spoof_testing": allow_spoof, "allow_voice_cloning": False})
    d = root / "Test Person"
    prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    prof["speaker_id"] = sid
    (d / "profile.json").write_text(json.dumps(prof), encoding="utf-8")
    cons = json.loads((d / "consent.json").read_text(encoding="utf-8"))
    cons.update(speaker_id=sid, signed=signed)
    (d / "consent.json").write_text(json.dumps(cons), encoding="utf-8")
    for n in numbers:
        write_wav(d / f"{n}.wav", sr=clip_sr)
    return root


def test_incoming_layout_passes_without_a_consent_dir(tmp_path, capsys):
    root = make_recorder_dir(tmp_path)
    assert vc.main(["--incoming", str(root), "--consent-dir", str(tmp_path / "nothing")]) == 0
    out = capsys.readouterr().out
    assert "PASS: 3/3" in out and "Test Person/1.wav" in out and "k7f3q9xa" in out


def test_incoming_layout_consent_and_audio_failures(tmp_path, capsys):
    unsigned = make_recorder_dir(tmp_path / "a", signed=False)
    assert vc.main(["--incoming", str(unsigned)]) == 1 and "not signed" in capsys.readouterr().out
    nospoof = make_recorder_dir(tmp_path / "b", allow_spoof=False)
    assert vc.main(["--incoming", str(nospoof)]) == 0
    assert vc.main(["--incoming", str(nospoof), "--allow-spoof-testing"]) == 1
    assert "spoof testing not allowed" in capsys.readouterr().out
    badrate = make_recorder_dir(tmp_path / "c", clip_sr=44100)
    assert vc.main(["--incoming", str(badrate)]) == 1 and "sample rate 44100" in capsys.readouterr().out
    (nospoof / "Test Person" / "consent.json").unlink()
    assert vc.main(["--incoming", str(nospoof)]) == 1 and "no consent record" in capsys.readouterr().out


def test_incoming_layout_empty_folder_fails_and_args_validated(tmp_path, capsys):
    assert vc.main(["--incoming", str(tmp_path)]) == 1
    assert "no clips found" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        vc.parse_args([])


def test_incoming_mismatched_consent_speaker_is_refused(tmp_path, capsys):
    root = make_recorder_dir(tmp_path)
    cons = json.loads((root / "Test Person" / "consent.json").read_text(encoding="utf-8"))
    cons["speaker_id"] = "someoneelse"
    (root / "Test Person" / "consent.json").write_text(json.dumps(cons), encoding="utf-8")
    assert vc.main(["--incoming", str(root)]) == 1 and "another speaker id" in capsys.readouterr().out


def test_master_manifest_with_bom_still_loads(tmp_path):
    manifest, consent, audio = make_session(tmp_path)
    manifest.write_text("﻿" + manifest.read_text(encoding="utf-8"), encoding="utf-8")
    assert run(manifest, consent, audio) == 0


# ---- rounds: _r<N> in the file name, (speaker, phrase, round) is the key ----
def test_rounds_are_not_duplicates_and_extra_columns_are_ignored(tmp_path, capsys):
    audio, consent = tmp_path / "audio", tmp_path / "consent"
    audio.mkdir()
    save_consent(ConsentRecord(speaker_id="LP1_01", full_name="T", signed=True), consent)
    manifest = tmp_path / "manifest_LP1.csv"
    cols = vc.REQUIRED_COLUMNS + ["full_name", "round", "user_agent"]
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for rnd in (1, 2):
            name = f"LP1_01__p001_hi_r{rnd}.wav"
            w.writerow(["LP1_01", "p001_hi", "hindi", "Hindi-belt", "25-34", "", "laptop", "2.00", name, "Asha", rnd, "UA; x"])
            write_wav(audio / name)
    assert run(manifest, consent, audio) == 0
    assert "PASS: 2/2" in capsys.readouterr().out


def test_same_round_twice_is_a_duplicate_and_old_names_are_round_one(tmp_path, capsys):
    manifest, consent, audio = make_session(tmp_path)  # spk01__p0.wav, no round column
    assert vc.row_round({"file": "spk01__p0.wav"}) == "1" and vc.row_round({"file": "a__b_r4.wav"}) == "4"
    assert vc.row_round({"file": "a__b_r4.wav", "round": "2"}) == "2"
    lines = manifest.read_text(encoding="utf-8").splitlines(True)
    manifest.write_text("".join(lines + [lines[1].replace("spk01__p0.wav", "spk01__p0_r1.wav")]), encoding="utf-8")
    write_wav(audio / "spk01__p0_r1.wav")
    assert run(manifest, consent, audio) == 1  # p0 round 1 (old name) and p0 round 1 (_r1 name) are the same key
    assert "duplicate row" in capsys.readouterr().out
