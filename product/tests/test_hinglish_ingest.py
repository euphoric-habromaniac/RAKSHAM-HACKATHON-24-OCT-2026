import csv
import json
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from service.consent import ConsentRecord, save_consent
from tools import ingest_hinglish as I
from tools.hinglish_data import read_manifest


def tone(path, freq, secs=2.0, lead=0.5):
    t = np.arange(int(secs * 16000)) / 16000
    x = 0.3 * np.sin(2 * np.pi * freq * t)
    x = np.concatenate([np.zeros(int(lead * 16000)), x, np.zeros(int(lead * 16000))])
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x.astype(np.float32), 16000)


def consent(d, spk, spoof=True, signed=True, rec=True):
    save_consent(ConsentRecord(speaker_id=spk, full_name="T", signed=signed, allow_recording=rec,
                               allow_spoof_testing=spoof), d)


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "in", tmp_path / "out", tmp_path / "consent"


def test_ingest_converts_trims_and_normalises(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    tone(inc / "s1__p01.wav", 220)
    assert I.run(inc, out, cons) == 0
    rows = read_manifest(out / "manifest.csv")
    assert [r["utt_id"] for r in rows] == ["bf__s1__p01"]
    f = str(out / "wav" / "bf__s1__p01.wav")
    x, sr = sf.read(f)
    info = sf.info(f)
    assert sr == 16000 and info.channels == 1 and info.subtype == "PCM_16"
    assert 2.0 <= len(x) / sr < 2.5  # 3 s with 0.5 s silence each side, trimmed to speech + margin
    assert abs(np.abs(x).max() - 0.9) < 0.01


def test_mp3_and_webm_and_resample(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    tone(inc / "src.wav", 300)
    for ext in ("mp3", "webm"):
        subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-y", "-i", str(inc / "src.wav"),
                        "-ar", "48000", str(inc / f"s1__p_{ext}.{ext}")], check=True)
    (inc / "src.wav").unlink()
    assert I.run(inc, out, cons) == 0
    assert len(read_manifest(out / "manifest.csv")) == 2


def test_refuses_without_consent_and_spoof_needs_flag(dirs):
    inc, out, cons = dirs
    consent(cons, "ok")
    consent(cons, "nospoof", spoof=False)
    consent(cons, "unsigned", signed=False)
    tone(inc / "ok__p1.wav", 200)
    tone(inc / "stranger__p1.wav", 210)
    tone(inc / "unsigned__p1.wav", 220)
    tone(inc / "nospoof__p1.wav", 230)
    tone(inc / "spoof" / "nospoof__p1.wav", 240)
    tone(inc / "spoof" / "ok__p1.wav", 250)
    assert I.run(inc, out, cons) == 1  # something was refused
    got = {r["utt_id"] for r in read_manifest(out / "manifest.csv")}
    assert got == {"bf__ok__p1", "bf__nospoof__p1", "sp__ok__p1"}


def test_unsafe_speaker_id_refused(dirs):
    inc, out, cons = dirs
    tone(inc / "..evil__p1.wav", 200)
    assert I.run(inc, out, cons) == 1
    assert read_manifest(out / "manifest.csv") == []


def test_short_clip_rejected(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    tone(inc / "s1__short.wav", 200, secs=0.5, lead=0.1)
    tone(inc / "s1__long.wav", 210)
    I.run(inc, out, cons)
    assert [r["phrase_id"] for r in read_manifest(out / "manifest.csv")] == ["long"]


def test_idempotent_and_dedupes_and_adds_sessions(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    consent(cons, "s2")
    tone(inc / "s1__p1.wav", 200)
    tone(inc / "s1__p1_copy.wav", 200)  # same audio under another name: duplicate content
    I.run(inc, out, cons)
    first = (out / "manifest.csv").read_text()
    I.run(inc, out, cons)
    assert (out / "manifest.csv").read_text() == first
    assert len(list((out / "wav").glob("*.wav"))) == 1
    inc2 = inc.parent / "in2"
    tone(inc2 / "s2__p1.wav", 400)
    I.run(inc2, out, cons)
    assert len(read_manifest(out / "manifest.csv")) == 2


def test_manifest_csv_metadata_wins_over_filename(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    tone(inc / "weird_name.wav", 200)
    with open(inc / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["speaker_id", "phrase_id", "language", "accent_group", "age_band", "gender", "device",
                    "duration_s", "file"])
        w.writerow(["s1", "p07", "hinglish", "Punjabi", "20-29", "f", "phone", "2", "weird_name.wav"])
    assert I.run(inc, out, cons) == 0
    r = read_manifest(out / "manifest.csv")[0]
    assert (r["speaker_id"], r["phrase_id"], r["accent_group"], r["language"]) == ("s1", "p07", "Punjabi", "hinglish")


HEAD = ["speaker_id", "phrase_id", "language", "accent_group", "age_band", "gender", "device", "duration_s", "file"]


def write_manifest_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        w.writerows(rows)


def test_multiple_per_speaker_manifests_merge_and_dedupe(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    consent(cons, "s2")
    tone(inc / "s1__p1.wav", 200)
    tone(inc / "s2__p1.wav", 300)
    write_manifest_csv(inc / "manifest_s1.csv", [["s1", "p1", "hinglish", "Punjabi", "", "", "phone", "2", "s1__p1.wav"]])
    write_manifest_csv(inc / "manifest_s2.csv", [["s2", "p1", "english", "Bengali", "", "", "laptop", "2", "s2__p1.wav"],
                                                 ["s2", "p1", "english", "Dup", "", "", "laptop", "2", "s2__p1.wav"]])
    assert I.run(inc, out, cons) == 0
    acc = {r["speaker_id"]: r["accent_group"] for r in read_manifest(out / "manifest.csv")}
    assert acc == {"s1": "Punjabi", "s2": "Bengali"}


def test_plain_manifest_csv_still_read_alongside_per_speaker(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    consent(cons, "s2")
    tone(inc / "s1__p1.wav", 200)
    tone(inc / "s2__p1.wav", 300)
    write_manifest_csv(inc / "manifest.csv", [["s1", "p1", "hinglish", "Punjabi", "", "", "", "2", "s1__p1.wav"]])
    write_manifest_csv(inc / "manifest_s2.csv", [["s2", "p1", "english", "Tamil", "", "", "", "2", "s2__p1.wav"]])
    assert I.run(inc, out, cons) == 0
    assert {r["accent_group"] for r in read_manifest(out / "manifest.csv")} == {"Punjabi", "Tamil"}


def test_no_manifest_falls_back_to_filenames_and_consent_json(dirs):
    inc, out, cons = dirs
    consent(cons, "s1")
    tone(inc / "s1__p09.wav", 200)
    (inc / "s1.json").write_text(json.dumps({"speaker_id": "s1", "metadata": {"language": "hindi"}}), encoding="utf-8")
    assert I.run(inc, out, cons) == 0
    r = read_manifest(out / "manifest.csv")[0]
    assert (r["speaker_id"], r["phrase_id"], r["language"], r["label"]) == ("s1", "p09", "hindi", "bonafide")


def test_parse_name_rounds_and_old_names():
    assert I.parse_name("LP1_01__p001_hi_r2") == ("LP1_01", "p001_hi", 2)
    assert I.parse_name("LP1_01__p001_hi_r1") == ("LP1_01", "p001_hi", 1)
    assert I.parse_name("s1__p09") == ("s1", "p09", 1)
    assert I.parse_name("plain") == ("plain", "", 1)
    assert I.row_round({"file": "x__p_r3.wav"}) == 3 and I.row_round({"file": "x__p.wav", "round": "5"}) == 5


def test_rounds_are_kept_and_extra_manifest_columns_ignored(dirs):
    inc, out, cons = dirs
    consent(cons, "LP1_01")
    tone(inc / "LP1_01__p001_hi_r1.wav", 200)
    tone(inc / "LP1_01__p001_hi_r2.wav", 300)  # same phrase, second round, different audio
    with open(inc / "manifest_LP1.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEAD + ["full_name", "round", "session_id", "prompt_text", "user_agent"])
        for rnd in (1, 2):
            w.writerow(["LP1_01", "p001_hi", "hindi", "Punjabi", "25-34", "", "laptop", "2", f"LP1_01__p001_hi_r{rnd}.wav",
                        "Asha, Rao", rnd, "LP1-1", "text, with comma", "UA"])
    (inc / "people.csv").write_text("speaker_id,full_name" + chr(10) + "LP1_01,Asha" + chr(10), encoding="utf-8")
    assert I.run(inc, out, cons) == 0
    rows = read_manifest(out / "manifest.csv")
    assert [(r["utt_id"], r["phrase_id"]) for r in rows] == [("bf__LP1_01__p001_hi", "p001_hi"), ("bf__LP1_01__p001_hi_r2", "p001_hi")]
    assert {r["accent_group"] for r in rows} == {"Punjabi"}


def test_rounds_from_file_names_without_manifest(dirs):
    inc, out, cons = dirs
    consent(cons, "LP1_01")
    tone(inc / "LP1_01__p002_en_r1.wav", 210)
    tone(inc / "LP1_01__p002_en_r3.wav", 410)
    tone(inc / "LP1_01__p003_hg.wav", 510)  # old name: round 1
    assert I.run(inc, out, cons) == 0
    assert sorted(r["utt_id"] for r in read_manifest(out / "manifest.csv")) == [
        "bf__LP1_01__p002_en", "bf__LP1_01__p002_en_r3", "bf__LP1_01__p003_hg"]


# ---- recorder layout: <Speaker Name>/N.wav + profile.json + consent.json (tools/recorder) ----
def recorder_dir(tmp_path, numbers=(1, 2, 3), name="Test Person", **over):
    from recorder_helpers import FIELDS, make_wav
    from tools.recorder.store import RecorderStore
    root = tmp_path / "recordings_awaaz"
    st = RecorderStore(root)
    v = st.save_profile({**FIELDS, "name": name, **over})
    for n in numbers:
        st.save_clip(name, n, make_wav(2.0, freq=200 + 40 * n))
    return root, v["profile"]["speaker_id"]


def test_recorder_layout_ingest(tmp_path):
    inc, sid = recorder_dir(tmp_path, numbers=(1, 2, 3))
    out, cons = tmp_path / "out", tmp_path / "no_consent_dir"  # consent comes from the speaker folder, not from consent_dir
    assert I.run(inc, out, cons) == 0
    rows = read_manifest(out / "manifest.csv")
    assert sorted(r["utt_id"] for r in rows) == [f"bf__{sid}__p001_hi", f"bf__{sid}__p002_en", f"bf__{sid}__p003_hg"]
    r = {r["phrase_id"]: r for r in rows}
    assert r["p001_hi"]["language"] == "hindi" and r["p002_en"]["language"] == "english" and r["p003_hg"]["language"] == "hinglish"
    assert {x["speaker_id"] for x in rows} == {sid} and {x["label"] for x in rows} == {"bonafide"}
    assert {(x["accent_group"], x["age_band"], x["device"]) for x in rows} == {("Hindi-belt", "25-34", "laptop mic")}
    for x in rows:
        assert (out / x["file"]).exists() and sf.info(str(out / x["file"])).samplerate == 16000
    assert I.run(inc, out, cons) == 0  # idempotent
    assert len(read_manifest(out / "manifest.csv")) == 3


def test_recorder_layout_refuses_unsigned_or_foreign_consent(tmp_path):
    inc, sid = recorder_dir(tmp_path)
    cj = inc / "Test Person" / "consent.json"
    data = json.loads(cj.read_text(encoding="utf-8"))
    cj.write_text(json.dumps({**data, "signed": False}), encoding="utf-8")
    assert I.run(inc, tmp_path / "out", tmp_path / "c") == 1
    assert read_manifest(tmp_path / "out" / "manifest.csv") == []
    cj.write_text(json.dumps({**data, "speaker_id": "other"}), encoding="utf-8")
    assert I.run(inc, tmp_path / "out", tmp_path / "c") == 1
    cj.unlink()
    assert I.run(inc, tmp_path / "out", tmp_path / "c") == 1


def test_recorder_layout_ignores_non_clip_files_and_mixes_with_flat_files(tmp_path):
    inc, sid = recorder_dir(tmp_path, numbers=(7,))
    d = inc / "Test Person"
    (d / "007.wav").write_bytes(b"junk")  # not a clip name
    tone(inc / "flat1__p01.wav", 333)  # old flat layout in the same folder
    cons = tmp_path / "consent"
    consent(cons, "flat1")
    out = tmp_path / "out"
    assert I.run(inc, out, cons) == 0
    assert sorted(r["utt_id"] for r in read_manifest(out / "manifest.csv")) == sorted([f"bf__{sid}__p007_hi", "bf__flat1__p01"])


def test_recorder_layout_two_speakers_and_continued_speaker_keep_ids(tmp_path):
    inc, sid1 = recorder_dir(tmp_path, numbers=(1,), name="Asha Rao")
    from recorder_helpers import FIELDS, make_wav
    from tools.recorder.store import RecorderStore
    st = RecorderStore(inc)
    sid2 = st.save_profile({**FIELDS, "name": "Dev Patel", "accent_group": "Punjabi"})["profile"]["speaker_id"]
    st.save_clip("Dev Patel", 1, make_wav(2.0, freq=777))
    assert st.save_profile({**FIELDS, "name": "asha rao"})["profile"]["speaker_id"] == sid1
    st.save_clip("asha rao", 2, make_wav(2.0, freq=555))
    out = tmp_path / "out"
    assert I.run(inc, out, tmp_path / "c") == 0
    rows = read_manifest(out / "manifest.csv")
    assert {(r["speaker_id"], r["phrase_id"]) for r in rows} == {(sid1, "p001_hi"), (sid1, "p002_en"), (sid2, "p001_hi")}
    assert {r["accent_group"] for r in rows if r["speaker_id"] == sid2} == {"Punjabi"}
