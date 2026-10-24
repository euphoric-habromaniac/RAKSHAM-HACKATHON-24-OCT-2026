"""Filesystem logic of the recorder (no HTTP). Everything a clip needs to survive lives here.

Layout under the recordings dir (see README.txt that is written there):
    <Speaker Name>/N.wav  profile.json  consent.json     N = script sentence number 1..100, no padding
    manifest_master.csv  people.csv  _session_log.csv  SPEAKER_SCRIPT.txt  prompts.csv  README.txt
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import secrets
import struct
import sys
import tempfile
import threading
import time
import unicodedata
import wave
import zipfile
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tools.recorder import prompts as prompts_mod

RATE, CHANNELS, BITS = 16000, 1, 16
MIN_S, MAX_S = 0.5, 60.0          # accepted clip length (server side)
WARN_SHORT_S, CLIP_LEVEL, QUIET_PEAK = 1.5, 0.99, 0.02  # warnings only, the clip is still saved
PROMPT_COUNT = 100
MAX_NAME = 64
RETENTION_DAYS = 90
CONSENT_LANGS = ("en", "hi")

MANIFEST = "manifest_master.csv"
PEOPLE = "people.csv"
LOG = "_session_log.csv"
SCRIPT = "SPEAKER_SCRIPT.txt"
PROMPTS_CSV = "prompts.csv"
README = "README.txt"
ROOT_FILES = (MANIFEST, PEOPLE, LOG, SCRIPT, PROMPTS_CSV, README)

INGEST_COLS = ["speaker_id", "phrase_id", "language", "accent_group", "age_band", "gender", "device", "duration_s", "file"]
EXTRA_COLS = ["full_name", "sentence_number", "prompt_text", "topic", "sample_rate", "channels", "bit_depth", "peak",
              "rms_dbfs", "clipped", "warnings", "recorded_at_iso", "consent_file"]
MANIFEST_COLS = INGEST_COLS + EXTRA_COLS
PEOPLE_COLS = ["speaker_id", "full_name", "name_key", "age_band", "gender", "accent_group", "device", "consent_language",
               "first_seen_iso", "last_seen_iso", "clips_total"]
LOG_COLS = ["timestamp", "event", "speaker", "sentence_number", "detail"]

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_CLIP_FILE = re.compile(r"^([1-9]\d{0,2})\.wav$")
_ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


class StoreError(Exception):
    """An error that maps to an HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- names
def sanitise_name(name) -> str:
    """Typed full name -> a safe Windows folder name (Unicode kept). Raises StoreError(400)."""
    s = unicodedata.normalize("NFC", str(name or ""))
    s = _ILLEGAL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:MAX_NAME].strip(" .")
    if not s:
        raise StoreError(400, "Type the speaker's full name (letters and digits).")
    if s.split(".")[0].strip().upper() in _RESERVED:
        raise StoreError(400, f"'{s}' is a reserved Windows name; please type the full name.")
    if s.lower() in {f.lower() for f in ROOT_FILES}:
        raise StoreError(400, f"'{s}' is not allowed as a speaker name.")
    return s


def name_key(name) -> str:
    """Same key = same person: lowercase letters, digits and marks only, single spaces."""
    s = unicodedata.normalize("NFC", str(name or "")).lower()
    s = "".join(c if (unicodedata.category(c)[0] in "LNM" or c.isspace()) else "" for c in s)
    return re.sub(r"\s+", " ", s).strip()


def new_speaker_id(taken=()) -> str:
    """8 characters, lowercase letters and digits, first one a letter."""
    taken = set(taken)
    while True:
        sid = secrets.choice(_ID_CHARS[:26]) + "".join(secrets.choice(_ID_CHARS) for _ in range(7))
        if sid not in taken:
            return sid


# ---------------------------------------------------------------- low level io
def atomic_write(path: Path, data: bytes) -> None:
    """Write next to the target, fsync, then os.replace (retries briefly if Windows holds the target)."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def csv_text(cols: list, rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return buf.getvalue()


def read_csv(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def json_bytes(obj) -> bytes:
    return json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- wav
def inspect_wav(data: bytes) -> dict:
    """Validate PCM 16-bit mono 16 kHz, 0.5-60 s; return duration and level stats. Raises StoreError(400)."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, EOFError, struct.error) as exc:
        raise StoreError(400, f"Not a PCM WAV file ({exc}).")
    if (ch, width, rate) != (CHANNELS, BITS // 8, RATE):
        raise StoreError(400, f"WAV must be 16 kHz mono 16-bit PCM, got {rate} Hz, {ch} channel(s), {width * 8}-bit.")
    if len(raw) != frames * 2:
        raise StoreError(400, "WAV data is truncated.")
    dur = frames / RATE
    if not MIN_S <= dur <= MAX_S:
        raise StoreError(400, f"Clip length {dur:.2f} s is outside {MIN_S}-{MAX_S:.0f} s.")
    pcm = array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()
    peak = max(max(pcm), -min(pcm)) / 32767.0
    rms = (sum(x * x for x in pcm) / len(pcm)) ** 0.5 / 32767.0
    return {"duration_s": dur, "peak": min(peak, 1.0), "rms_dbfs": 20 * math.log10(rms) if rms > 0 else -120.0}


def clip_warnings(info: dict) -> list:
    out = []
    if info["duration_s"] < WARN_SHORT_S:
        out.append(f"too short ({info['duration_s']:.1f} s)")
    if info["peak"] >= CLIP_LEVEL:
        out.append("clipped")
    if info["peak"] < QUIET_PEAK:
        out.append("very quiet")
    return out


# ---------------------------------------------------------------- the store
class RecorderStore:
    def __init__(self, root, prompts: Optional[list] = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prompts = prompts if prompts is not None else prompts_mod.load_prompts()
        self.lock = threading.RLock()

    # ---- paths
    def _inside(self, path: Path) -> Path:
        p = path.resolve()
        try:
            p.relative_to(self.root)
        except ValueError:
            raise StoreError(400, "Path is outside the recordings folder.")
        if p == self.root:
            raise StoreError(400, "Invalid speaker folder.")
        return p

    def speaker_dirs(self) -> list:
        return sorted(d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith("."))

    def find_speaker_dir(self, name) -> Optional[Path]:
        """Existing folder of the same person (same name_key), else None."""
        key = name_key(name)
        if not key:
            return None
        try:
            direct = self._inside(self.root / sanitise_name(name))
        except StoreError:
            direct = None
        if direct and direct.is_dir() and name_key(read_json(direct / "profile.json").get("name", direct.name)) == key:
            return direct
        for d in self.speaker_dirs():
            prof = read_json(d / "profile.json")
            if prof and name_key(prof.get("name", "")) == key:
                return self._inside(d)
        return None

    def speaker_dir(self, name) -> Path:
        """Folder for this name (existing or to be created); always inside the recordings dir."""
        return self.find_speaker_dir(name) or self._inside(self.root / sanitise_name(name))

    def _existing(self, name) -> Path:
        d = self.find_speaker_dir(name)
        if d is None or not (d / "profile.json").exists():
            raise StoreError(404, "No profile for this speaker yet: create it first.")
        return d

    # ---- scanning
    @staticmethod
    def _numbers_in(d: Path) -> list:
        out = []
        for f in d.iterdir():
            m = _CLIP_FILE.match(f.name)
            if m and 1 <= int(m.group(1)) <= PROMPT_COUNT and f.is_file() and f.stat().st_size > 44:
                out.append(int(m.group(1)))
        return sorted(out)

    def done_numbers(self, speaker) -> list:
        """Sentence numbers that have a N.wav on disk (speaker = name; unknown name -> [])."""
        with self.lock:
            d = self.find_speaker_dir(speaker)
            return self._numbers_in(d) if d else []

    def _view(self, d: Path) -> dict:
        prof = read_json(d / "profile.json")
        prof["folder"] = d.name
        done = self._numbers_in(d)
        return {"profile": prof, "done": done, "done_count": len(done)}

    def list_speakers(self) -> list:
        with self.lock:
            out = []
            for d in self.speaker_dirs():
                v = self._view(d)
                p = v["profile"]
                if p.get("speaker_id"):
                    out.append({"name": p.get("name", d.name), "speaker_id": p["speaker_id"], "done": v["done_count"],
                                "last_seen": p.get("last_seen_iso", ""), "folder": d.name})
            return sorted(out, key=lambda s: s["last_seen"], reverse=True)

    def get_speaker(self, name) -> dict:
        with self.lock:
            return self._view(self._existing(name))

    def info(self) -> dict:
        return {"dir": str(self.root), "prompt_count": len(self.prompts)}

    # ---- profile + consent
    def _clean_fields(self, f: dict) -> dict:
        s = lambda k: str(f.get(k) or "").strip()[:100]  # noqa: E731
        if f.get("allow_recording") is not True:
            raise StoreError(400, "Recording consent must be ticked to continue.")
        return {"name": sanitise_name(f.get("name") or f.get("full_name")), "age_band": s("age_band"), "gender": s("gender"),
                "accent_group": s("accent_group"), "device": s("device"), "consent_language": s("consent_language"),
                "typed_name": str(f.get("name") or f.get("full_name") or "").strip()[:100],
                "allow_recording": True, "allow_spoof_testing": f.get("allow_spoof_testing") is True,
                "allow_voice_cloning": f.get("allow_voice_cloning") is True}

    def save_profile(self, fields: dict) -> dict:
        """Create the speaker or update the existing one (same name_key); writes profile.json and consent.json."""
        c = self._clean_fields(fields)
        with self.lock:
            d = self.find_speaker_dir(c["name"])
            existing = d is not None and (d / "profile.json").exists()
            d = d or self._inside(self.root / c["name"])
            prof = read_json(d / "profile.json") if existing else {}
            if not existing:
                missing = [k for k in ("age_band", "accent_group", "device", "consent_language") if not c[k]]
                if missing:
                    raise StoreError(400, "Fill age band, accent group, device and consent language.")
            if c["consent_language"] and c["consent_language"] not in CONSENT_LANGS:
                raise StoreError(400, "Consent form language must be en or hi.")
            d.mkdir(parents=True, exist_ok=True)
            now = now_iso()
            keep = {"name": c["name"] if not existing else prof.get("name", c["name"]),
                    "speaker_id": prof.get("speaker_id") or new_speaker_id(s["speaker_id"] for s in self.list_speakers()),
                    "created_iso": prof.get("created_iso") or now, "last_seen_iso": now}
            for k in ("age_band", "gender", "accent_group", "device", "consent_language"):
                keep[k] = c[k] or prof.get(k, "")
            atomic_write(d / "profile.json", json_bytes(keep))
            atomic_write(d / "consent.json", json_bytes(self._consent(d, keep, c, now)))
            self.append_log("continued" if existing else "profile_created", keep["name"], "", f"speaker_id {keep['speaker_id']}")
            self._write_people()
            out = self._view(d)
            out["existing"] = existing
            return out

    @staticmethod
    def _consent(d: Path, prof: dict, c: dict, now: str) -> dict:
        lang = prof["consent_language"]
        entry = {"signed_at": now, "typed_name": c["typed_name"], "consent_form_language": lang,
                 "allow_recording": True, "allow_spoof_testing": c["allow_spoof_testing"],
                 "allow_voice_cloning": c["allow_voice_cloning"]}
        history = read_json(d / "consent.json").get("metadata", {}).get("signed_history", []) + [entry]
        return {"speaker_id": prof["speaker_id"], "full_name": prof["name"], "signed": True, "signed_at": now,
                "allow_recording": True, "allow_spoof_testing": c["allow_spoof_testing"],
                "allow_voice_cloning": c["allow_voice_cloning"], "retention_days": RETENTION_DAYS,
                "metadata": {"language": lang, "form": f"consent_form_{lang}", "consent_form_language": lang,
                             "signed_at": now, "source": "recorder", "signed_history": history}}

    def touch(self, name) -> dict:
        """Continue a speaker: bump last_seen and log it."""
        with self.lock:
            d = self._existing(name)
            prof = read_json(d / "profile.json")
            prof["last_seen_iso"] = now_iso()
            atomic_write(d / "profile.json", json_bytes(prof))
            self.append_log("continued", prof["name"], "", f"{len(self._numbers_in(d))} of {PROMPT_COUNT} already saved")
            self._write_people()
            return self._view(d)

    # ---- clips
    def save_clip(self, name, n, data: bytes) -> dict:
        """Validate and write <speaker>/<n>.wav atomically, then update manifest, people and log."""
        n = self._number(n)
        info = inspect_wav(data)
        with self.lock:
            d = self._existing(name)
            target = self._inside(d / f"{n}.wav")
            redo = target.exists()
            try:
                atomic_write(target, data)
                if target.stat().st_size != len(data):
                    raise OSError("size check after write failed")
            except OSError as exc:
                self._safe_log("save_failed", d.name, n, str(exc))
                raise StoreError(500, f"Could not write the clip to disk: {exc}")
            prof = read_json(d / "profile.json")
            warnings = clip_warnings(info)
            manifest_ok = True
            try:
                self.update_manifest(self._row(d, prof, n, info, warnings))
                self._write_people()
            except OSError as exc:
                manifest_ok = False
                self._safe_log("save_failed", d.name, n, f"clip saved, tables not updated: {exc}")
            self._safe_log("clip_redo" if redo else "clip_saved", prof.get("name", d.name), n, f"{info['duration_s']:.2f}s {len(data)} bytes")
            touched = dict(prof, last_seen_iso=now_iso())
            try:
                atomic_write(d / "profile.json", json_bytes(touched))
            except OSError:
                pass
            return {"ok": True, "n": n, "size": len(data), "done_count": len(self._numbers_in(d)), "warnings": warnings,
                    "redo": redo, "manifest_ok": manifest_ok}

    @staticmethod
    def _number(n) -> int:
        try:
            v = int(str(n).strip())
        except (TypeError, ValueError):
            raise StoreError(400, "Sentence number must be an integer 1-100.")
        if not 1 <= v <= PROMPT_COUNT:
            raise StoreError(400, f"Sentence number must be 1-{PROMPT_COUNT}.")
        return v

    def clip_path(self, name, n) -> Path:
        n = self._number(n)
        p = self._existing(name) / f"{n}.wav"
        if not p.exists():
            raise StoreError(404, "No saved take for this sentence.")
        return self._inside(p)

    def read_clip(self, name, n) -> bytes:
        with self.lock:
            return self.clip_path(name, n).read_bytes()

    def _row(self, d: Path, prof: dict, n: int, info: dict, warnings: list) -> dict:
        p = prompts_mod.prompt_by_number(self.prompts, n)
        return {"speaker_id": prof.get("speaker_id", ""), "phrase_id": p.get("id", ""), "language": p.get("lang", ""),
                "accent_group": prof.get("accent_group", ""), "age_band": prof.get("age_band", ""), "gender": prof.get("gender", ""),
                "device": prof.get("device", ""), "duration_s": f"{info['duration_s']:.2f}", "file": f"{d.name}/{n}.wav",
                "full_name": prof.get("name", d.name), "sentence_number": str(n), "prompt_text": p.get("text", ""),
                "topic": p.get("topic", ""), "sample_rate": str(RATE), "channels": str(CHANNELS), "bit_depth": str(BITS),
                "peak": f"{info['peak']:.4f}", "rms_dbfs": f"{info['rms_dbfs']:.1f}",
                "clipped": "true" if info["peak"] >= CLIP_LEVEL else "false", "warnings": "; ".join(warnings),
                "recorded_at_iso": now_iso(), "consent_file": f"{d.name}/consent.json"}

    # ---- tables (all rewritten atomically)
    def update_manifest(self, row: dict) -> None:
        """Replace the row of the same file (redo) or append; manifest_master.csv is rewritten atomically."""
        with self.lock:
            rows = read_csv(self.root / MANIFEST)
            for i, r in enumerate(rows):
                if r.get("file") == row["file"]:
                    rows[i] = row
                    break
            else:
                rows.append(row)
            atomic_write(self.root / MANIFEST, csv_text(MANIFEST_COLS, rows).encode("utf-8-sig"))

    def people_rows(self) -> list:
        rows = []
        for d in self.speaker_dirs():
            p = read_json(d / "profile.json")
            if not p.get("speaker_id"):
                continue
            rows.append({"speaker_id": p["speaker_id"], "full_name": p.get("name", d.name), "name_key": name_key(p.get("name", d.name)),
                         "age_band": p.get("age_band", ""), "gender": p.get("gender", ""), "accent_group": p.get("accent_group", ""),
                         "device": p.get("device", ""), "consent_language": p.get("consent_language", ""),
                         "first_seen_iso": p.get("created_iso", ""), "last_seen_iso": p.get("last_seen_iso", ""),
                         "clips_total": str(len(self._numbers_in(d)))})
        return rows

    def _write_people(self) -> None:
        atomic_write(self.root / PEOPLE, csv_text(PEOPLE_COLS, self.people_rows()).encode("utf-8-sig"))

    def append_log(self, event: str, speaker="", n="", detail="") -> None:
        """Append one line to _session_log.csv and fsync it."""
        path = self.root / LOG
        with self.lock:
            fresh = not path.exists() or path.stat().st_size == 0
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            if fresh:
                w.writerow(LOG_COLS)
            w.writerow([now_iso(), event, speaker, n, detail])
            with open(path, "ab") as f:
                f.write(buf.getvalue().encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())

    def _safe_log(self, *args) -> None:
        try:
            self.append_log(*args)
        except OSError:
            pass

    # ---- reference files and zip
    def readme_text(self) -> str:
        def cols(names):
            return "\n".join(f"    {c}: {COLUMN_DOC.get(c, '')}" for c in names)
        files = [
            "<Speaker Name>/N.wav  one clip, 16 kHz mono 16-bit. N is the sentence number (1..100) in SPEAKER_SCRIPT.txt. A redo overwrites it.",
            "<Speaker Name>/profile.json  name, speaker_id (random, assigned once), age band, gender, accent group, device, consent language.",
            "<Speaker Name>/consent.json  consent record written when the speaker signs (metadata.signed_history keeps every signing).",
            f"{MANIFEST}  one row per saved clip, rewritten after every clip. The first 9 columns are the ingest columns.",
            f"{PEOPLE}  one row per speaker.", f"{LOG}  append-only event log.",
            f"{SCRIPT}, {PROMPTS_CSV}  the 100 sentences, numbered.", f"{README}  this file.",
            "Which clips are done is decided by the files on disk: a clip counts as done when N.wav exists.",
        ]
        return "\n".join(["ASLI AWAAZ - RECORDINGS", "", "FILES", *("  " + f for f in files), "", f"COLUMNS of {MANIFEST}", cols(MANIFEST_COLS), "",
                          f"COLUMNS of {PEOPLE}", cols(PEOPLE_COLS), "", f"COLUMNS of {LOG}", cols(LOG_COLS), ""])

    def write_reference_files(self) -> None:
        with self.lock:
            atomic_write(self.root / SCRIPT, b"\xef\xbb\xbf" + prompts_mod.script_text(self.prompts).encode("utf-8"))
            atomic_write(self.root / PROMPTS_CSV, b"\xef\xbb\xbf" + prompts_mod.prompts_csv(self.prompts).encode("utf-8"))
            atomic_write(self.root / README, self.readme_text().encode("utf-8"))

    def build_zip(self, speaker=None):
        """Zip of one speaker (name) or of the whole recordings dir. Returns a seekable file at position 0."""
        out = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
        with self.lock, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            if speaker:
                d = self._existing(speaker)
                dirs, prof = [d], read_json(d / "profile.json")
                tables = self._tables_for(d, prof)
            else:
                dirs = self.speaker_dirs()
                tables = [(f, (self.root / f).read_bytes()) for f in (MANIFEST, PEOPLE, LOG) if (self.root / f).exists()]
            for d in dirs:
                for f in sorted(d.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        z.write(f, f"{d.name}/{f.name}")
            for arc, data in tables + self._reference_files():
                z.writestr(arc, data)
        out.seek(0)
        return out

    def _tables_for(self, d: Path, prof: dict) -> list:
        sid, name = prof.get("speaker_id"), prof.get("name", d.name)
        man = [r for r in read_csv(self.root / MANIFEST) if r.get("speaker_id") == sid]
        ppl = [r for r in self.people_rows() if r["speaker_id"] == sid]
        log = [r for r in read_csv(self.root / LOG) if r.get("speaker") in (name, d.name)]
        return [(MANIFEST, csv_text(MANIFEST_COLS, man).encode("utf-8-sig")), (PEOPLE, csv_text(PEOPLE_COLS, ppl).encode("utf-8-sig")),
                (LOG, csv_text(LOG_COLS, log).encode("utf-8-sig"))]

    def _reference_files(self) -> list:
        return [(SCRIPT, b"\xef\xbb\xbf" + prompts_mod.script_text(self.prompts).encode("utf-8")),
                (PROMPTS_CSV, b"\xef\xbb\xbf" + prompts_mod.prompts_csv(self.prompts).encode("utf-8")),
                (README, self.readme_text().encode("utf-8"))]


COLUMN_DOC = {
    "speaker_id": "random 8-character id, assigned once when the profile is created", "phrase_id": "prompt id, e.g. p001_hi (hi/en/hg = language)",
    "language": "prompt language: hindi, english or hinglish", "accent_group": "accent / region group chosen by the speaker",
    "age_band": "age band chosen by the speaker", "gender": "gender chosen by the speaker (may be empty)",
    "device": "device / microphone typed by the speaker", "duration_s": "clip length in seconds",
    "file": "clip path relative to the recordings folder: <Speaker Name>/N.wav", "full_name": "full name typed by the speaker",
    "sentence_number": "N, the number of the sentence in the script", "prompt_text": "the exact text shown", "topic": "prompt topic",
    "sample_rate": "Hz", "channels": "number of channels", "bit_depth": "bits per sample", "peak": "highest absolute sample (0-1)",
    "rms_dbfs": "average level in dB below full scale", "clipped": "true if the clip hit full scale",
    "warnings": "warnings noticed on the take (may be empty)", "recorded_at_iso": "time the clip was saved (UTC)",
    "consent_file": "consent JSON of this speaker", "name_key": "normalised name: same key = same person",
    "consent_language": "language of the consent form signed", "first_seen_iso": "profile creation time",
    "last_seen_iso": "latest signing or clip time", "clips_total": "N.wav files on disk for this speaker",
    "timestamp": "event time (UTC)", "event": "profile_created, continued, clip_saved, clip_redo, zip_built or save_failed",
    "speaker": "full name", "detail": "free text",
}
