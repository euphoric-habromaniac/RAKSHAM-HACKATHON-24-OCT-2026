import csv
import io
import json
import zipfile

import pytest

from recorder_helpers import FIELDS, make_wav
from tools.recorder import prompts as prompts_mod
from tools.recorder import store as S
from tools.recorder.store import RecorderStore, StoreError


@pytest.fixture
def st(tmp_path):
    return RecorderStore(tmp_path / "rec")


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---- names
def test_sanitise_strips_illegal_chars_and_keeps_unicode():
    assert S.sanitise_name('  Yash <C>hauhan: "x"|?*  ') == "Yash Chauhan x"
    assert S.sanitise_name("सुनीता   वर्मा") == "सुनीता वर्मा"
    assert S.sanitise_name("name. . ") == "name"
    assert S.sanitise_name("a\x00b\x1fc") == "abc"
    assert len(S.sanitise_name("x" * 200)) == 64


@pytest.mark.parametrize("bad", ["", "   ", "...", '<>:"/\\|?*', "CON", "nul", "Com1", "lpt9.txt", "aux ", "manifest_master.csv", "People.csv"])
def test_sanitise_rejects_empty_and_reserved(bad):
    with pytest.raises(StoreError) as e:
        S.sanitise_name(bad)
    assert e.value.status == 400


@pytest.mark.parametrize("evil", ["../x", "..\\..\\evil", "/etc/passwd", "C:\\Windows", "a/../../b", "..", "...."])
def test_traversal_names_stay_inside_the_recordings_dir(st, evil):
    try:
        d = st.speaker_dir(evil)
    except StoreError:
        return
    assert d.resolve().parent == st.root  # one plain folder directly under the recordings dir
    assert "/" not in d.name and "\\" not in d.name and d.name not in (".", "..")


def test_name_key_links_same_person():
    assert S.name_key("  ASHA   rao! ") == S.name_key("asha rao")
    assert S.name_key("सुनीता वर्मा") == "सुनीता वर्मा"  # combining marks survive
    assert S.name_key("a") != S.name_key("b")


def test_speaker_ids_are_random_and_well_formed():
    ids = {S.new_speaker_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i) == 8 and i[0].isalpha() and i.isalnum() and i == i.lower() for i in ids)
    assert S.new_speaker_id(taken=ids) not in ids


# ---- profile
def test_profile_create_writes_files_and_continue_keeps_id(st):
    v = st.save_profile(FIELDS)
    assert v["existing"] is False and v["done"] == []
    d = st.root / "Test Person"
    prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    assert set(prof) >= {"name", "speaker_id", "age_band", "gender", "accent_group", "device", "consent_language", "created_iso", "last_seen_iso"}
    sid = prof["speaker_id"]
    assert len(sid) == 8 and sid[0].isalpha()
    again = st.save_profile({**FIELDS, "name": "test  PERSON", "device": "usb mic"})
    assert again["existing"] is True and again["profile"]["speaker_id"] == sid
    assert again["profile"]["name"] == "Test Person" and again["profile"]["device"] == "usb mic"
    assert [p.name for p in st.root.iterdir() if p.is_dir()] == ["Test Person"]  # no second folder


def test_consent_json_is_a_valid_consent_record_with_history(st):
    from service.consent import ConsentRecord
    st.save_profile(FIELDS)
    st.save_profile({**FIELDS, "allow_voice_cloning": True})
    raw = json.loads((st.root / "Test Person" / "consent.json").read_text(encoding="utf-8"))
    rec = ConsentRecord.model_validate(raw)
    sid = json.loads((st.root / "Test Person" / "profile.json").read_text(encoding="utf-8"))["speaker_id"]
    assert rec.speaker_id == sid and rec.signed and rec.allow_recording and rec.allow_voice_cloning and rec.retention_days == 90
    m = rec.metadata
    assert m["source"] == "recorder" and m["language"] == "en" and m["form"] == "consent_form_en" and len(m["signed_history"]) == 2
    assert m["signed_history"][0]["allow_voice_cloning"] is False


@pytest.mark.parametrize("change", [{"allow_recording": False}, {"name": ""}, {"age_band": ""}, {"device": ""}, {"consent_language": "fr"}])
def test_profile_validation(st, change):
    with pytest.raises(StoreError) as e:
        st.save_profile({**FIELDS, **change})
    assert e.value.status == 400
    assert st.list_speakers() == []


# ---- clips
def test_save_clip_atomic_write_and_done_scan(st):
    st.save_profile(FIELDS)
    assert st.done_numbers("Test Person") == []
    for n in (1, 2, 3, 100):
        r = st.save_clip("Test Person", n, make_wav(1.0 + n / 100))
        assert r["ok"] and r["n"] == n
    assert st.done_numbers("Test Person") == [1, 2, 3, 100]
    d = st.root / "Test Person"
    assert (d / "1.wav").stat().st_size == len(make_wav(1.01))
    assert not [p for p in d.iterdir() if p.name.endswith(".tmp")]
    (d / "007.wav").write_bytes(b"x" * 100)  # padded names and out-of-range numbers are not clips
    (d / "101.wav").write_bytes(b"x" * 100)
    (d / "0.wav").write_bytes(b"x" * 100)
    assert st.done_numbers("Test Person") == [1, 2, 3, 100]


def test_done_scan_survives_a_new_store_object(st, tmp_path):
    st.save_profile(FIELDS)
    st.save_clip("Test Person", 5, make_wav())
    fresh = RecorderStore(tmp_path / "rec")
    assert fresh.done_numbers("Test Person") == [5] and fresh.get_speaker("test person")["done"] == [5]


@pytest.mark.parametrize("kwargs,msg", [({"rate": 44100}, "16 kHz"), ({"channels": 2}, "mono"), ({"width": 1}, "16-bit"),
                                         ({"seconds": 0.2}, "outside"), ({"seconds": 61}, "outside")])
def test_save_clip_rejects_wrong_format(st, kwargs, msg):
    st.save_profile(FIELDS)
    with pytest.raises(StoreError) as e:
        st.save_clip("Test Person", 1, make_wav(**kwargs))
    assert e.value.status == 400 and msg in e.value.message
    assert st.done_numbers("Test Person") == []


@pytest.mark.parametrize("data", [b"", b"not a wav at all", make_wav()[:100], b"RIFF" + b"\x00" * 40])
def test_save_clip_rejects_garbage(st, data):
    st.save_profile(FIELDS)
    with pytest.raises(StoreError) as e:
        st.save_clip("Test Person", 1, data)
    assert e.value.status == 400


@pytest.mark.parametrize("n", [0, 101, -1, "x", "1.5", None, "../1"])
def test_save_clip_rejects_bad_numbers(st, n):
    st.save_profile(FIELDS)
    with pytest.raises(StoreError) as e:
        st.save_clip("Test Person", n, make_wav())
    assert e.value.status == 400


def test_save_clip_needs_a_profile_and_stays_inside(st):
    with pytest.raises(StoreError) as e:
        st.save_clip("Nobody", 1, make_wav())
    assert e.value.status == 404
    with pytest.raises(StoreError):
        st.save_clip("../../evil", 1, make_wav())
    assert not any(p.name == "evil" for p in st.root.parent.parent.iterdir())


def test_redo_overwrites_file_and_row(st):
    st.save_profile(FIELDS)
    st.save_clip("Test Person", 2, make_wav(1.0))
    r = st.save_clip("Test Person", 2, make_wav(3.0))
    assert r["redo"] is True and r["done_count"] == 1
    assert (st.root / "Test Person" / "2.wav").read_bytes() == make_wav(3.0)
    m = rows(st.root / S.MANIFEST)
    assert len(m) == 1 and m[0]["duration_s"] == "3.00"
    events = [e["event"] for e in rows(st.root / S.LOG)]
    assert events == ["profile_created", "clip_saved", "clip_redo"]


def test_manifest_columns_order_and_content(st):
    st.save_profile(FIELDS)
    sid = st.get_speaker("Test Person")["profile"]["speaker_id"]
    for n in (1, 2, 3):
        st.save_clip("Test Person", n, make_wav(2.0))
    st.save_clip("Test Person", 4, make_wav(1.0, amp=0.001))
    raw = (st.root / S.MANIFEST).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM so Excel shows Devanagari correctly
    text = raw.decode("utf-8-sig")
    first9 = "speaker_id,phrase_id,language,accent_group,age_band,gender,device,duration_s,file".split(",")
    extras = ("full_name,sentence_number,prompt_text,topic,sample_rate,channels,bit_depth,peak,rms_dbfs,clipped,warnings,"
              "recorded_at_iso,consent_file").split(",")
    assert text.splitlines()[0] == ",".join(first9 + extras) and S.MANIFEST_COLS == first9 + extras
    m = rows(st.root / S.MANIFEST)
    assert [r["file"] for r in m] == [f"Test Person/{n}.wav" for n in (1, 2, 3, 4)]
    r = m[1]
    p2 = prompts_mod.load_prompts()[1]
    assert (r["speaker_id"], r["phrase_id"], r["language"], r["device"], r["duration_s"]) == (sid, "p002_en", "english", "laptop mic", "2.00")
    assert (r["full_name"], r["sentence_number"], r["prompt_text"], r["topic"]) == ("Test Person", "2", p2["text"], p2["topic"])
    assert (r["sample_rate"], r["channels"], r["bit_depth"], r["clipped"], r["consent_file"]) == ("16000", "1", "16", "false", "Test Person/consent.json")
    assert "very quiet" in m[3]["warnings"] and "too short" in m[3]["warnings"]
    assert float(r["peak"]) == pytest.approx(0.3, abs=0.01) and float(r["rms_dbfs"]) < 0


def test_people_csv_and_log(st):
    st.save_profile(FIELDS)
    st.save_profile({**FIELDS, "name": "Asha Rao", "accent_group": "Punjabi"})
    st.save_clip("Test Person", 1, make_wav())
    st.save_clip("Test Person", 2, make_wav())
    people = rows(st.root / S.PEOPLE)
    assert list(people[0]) == S.PEOPLE_COLS
    by = {p["full_name"]: p for p in people}
    assert by["Test Person"]["clips_total"] == "2" and by["Asha Rao"]["clips_total"] == "0"
    assert by["Asha Rao"]["accent_group"] == "Punjabi" and by["Asha Rao"]["name_key"] == "asha rao"
    assert len({p["speaker_id"] for p in people}) == 2
    log = rows(st.root / S.LOG)
    assert list(log[0]) == S.LOG_COLS
    assert [e["event"] for e in log] == ["profile_created", "profile_created", "clip_saved", "clip_saved"]
    assert log[2]["speaker"] == "Test Person" and log[2]["sentence_number"] == "1"


def test_list_speakers_and_continue_touch(st, monkeypatch):
    ticks = iter(f"2026-01-01T00:00:{i:02d}+00:00" for i in range(60))
    monkeypatch.setattr(S, "now_iso", lambda: next(ticks))
    st.save_profile(FIELDS)
    st.save_clip("Test Person", 1, make_wav())
    st.save_profile({**FIELDS, "name": "Asha Rao"})
    ls = st.list_speakers()
    assert {s["name"]: s["done"] for s in ls} == {"Test Person": 1, "Asha Rao": 0}
    v = st.touch("test person")
    assert v["done"] == [1] and "continued" in [e["event"] for e in rows(st.root / S.LOG)]
    assert st.list_speakers()[0]["name"] == "Test Person"  # most recently seen first
    with pytest.raises(StoreError) as e:
        st.touch("Nobody")
    assert e.value.status == 404


# ---- reference files and zip
def test_reference_files(st):
    st.write_reference_files()
    assert (st.root / S.SCRIPT).read_bytes().startswith(b"\xef\xbb\xbf")
    assert (st.root / S.SCRIPT).read_text(encoding="utf-8-sig") == prompts_mod.script_text(prompts_mod.load_prompts())
    assert len(rows(st.root / S.PROMPTS_CSV)) == 100
    readme = (st.root / S.README).read_text(encoding="utf-8")
    for col in S.MANIFEST_COLS + S.PEOPLE_COLS + S.LOG_COLS + list(S.ROOT_FILES) + ["profile.json", "consent.json", "N.wav", "signed_history"]:
        assert col in readme, col


def test_build_zip_whole_and_single(st):
    st.save_profile(FIELDS)
    st.save_profile({**FIELDS, "name": "सुनीता वर्मा"})
    for n in (1, 2):
        st.save_clip("Test Person", n, make_wav())
    st.save_clip("सुनीता वर्मा", 7, make_wav())
    z = zipfile.ZipFile(st.build_zip())
    assert z.testzip() is None
    names = set(z.namelist())
    assert {"Test Person/1.wav", "Test Person/2.wav", "Test Person/profile.json", "Test Person/consent.json", "सुनीता वर्मा/7.wav",
            "सुनीता वर्मा/profile.json", "manifest_master.csv", "people.csv", "_session_log.csv", "SPEAKER_SCRIPT.txt", "prompts.csv",
            "README.txt"} <= names
    assert not [n for n in names if n.endswith(".tmp") or "/." in n]
    assert z.read("Test Person/1.wav") == make_wav()
    assert len(list(csv.DictReader(io.StringIO(z.read("manifest_master.csv").decode("utf-8"))))) == 3

    one = zipfile.ZipFile(st.build_zip("test person"))
    n1 = set(one.namelist())
    assert "Test Person/2.wav" in n1 and not any(n.startswith("सुनीता") for n in n1)
    assert {"manifest_master.csv", "people.csv", "_session_log.csv", "SPEAKER_SCRIPT.txt", "prompts.csv", "README.txt"} <= n1
    man = list(csv.DictReader(io.StringIO(one.read("manifest_master.csv").decode("utf-8"))))
    assert len(man) == 2 and all(r["full_name"] == "Test Person" for r in man)
    assert "सुनीता" not in one.read("people.csv").decode("utf-8") + one.read("_session_log.csv").decode("utf-8")
    with pytest.raises(StoreError):
        st.build_zip("Nobody")


def test_info(st):
    assert st.info() == {"dir": str(st.root), "prompt_count": 100}
