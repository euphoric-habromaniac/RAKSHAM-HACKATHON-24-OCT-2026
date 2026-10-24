"""Ingest dropped Hinglish recordings into data/hinglish (wav/ + manifest.csv).

    python -m tools.ingest_hinglish --incoming data/hinglish_incoming/<session> --out data/hinglish

Input layout 1 (tools/recorder, e.g. downloads/recordings_awaaz or an unzipped zip):
    <Speaker Name>/N.wav  profile.json  consent.json     N = sentence number 1..100
    speaker id: profile.json; consent: the folder's consent.json; phrase id: tools/recorder/prompts.json by N.
Input layout 2 (older flat sessions, still supported; folders that have a profile.json are read as layout 1):
    <speaker_id>__<phrase_id>_r<round>.<wav|flac|mp3|m4a|webm>   in the root or in bonafide/ (old names
        <speaker_id>__<phrase_id>.<ext> without _r<N> still work and count as round 1)
    spoof/<speaker_id>__<phrase_id>.<ext>               clone audio, speaker_id = the voice that was cloned
    manifest*.csv (optional): speaker_id,phrase_id,language,accent_group,age_band,gender,device,duration_s,file
        [+ extra columns such as round, full_name ... which are ignored except `round`]
        older recorder pages wrote manifest_<station>.csv; all manifest*.csv files in the folder are
        merged (deduped by speaker/phrase/round; a plain manifest.csv still works). `file` is relative to the
        session folder; rows win over what the file name says. With no manifest, rows come from the file
        names, and `language` from <speaker_id>.json (consent metadata) when it sits in the folder.

Rules: a speaker with no signed consent record (service.consent) is refused;
the record must allow_recording, and allow_spoof_testing for the spoof/ folder.
Clips are decoded with ffmpeg to 16 kHz mono, lightly trimmed, rejected if
under 1.0 s, peak-normalised and de-duplicated by content hash. Safe to rerun
with more sessions: existing clips are kept, the manifest is rewritten.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service.consent import CONSENT_DIR, get_consent  # noqa: E402
from tools.hinglish_data import DEFAULT_DIR, UNKNOWN, read_manifest, write_manifest  # noqa: E402
from tools.recorder import layout  # noqa: E402

SR = 16000
EXTS = {".wav", ".flac", ".mp3", ".m4a", ".webm"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")  # also keeps ids safe as file names
ROUND_RE = re.compile(r"^(.+)_r(\d+)$")  # phrase part of a file name: p001_hi_r2
META = ["language", "accent_group", "age_band", "gender", "device"]
TRIM_DB, PAD_S, MIN_S, PEAK = -40.0, 0.15, 1.0, 0.9


# ------------------------------------------------------------ discovery
def label_of(path: Path, incoming: Path) -> str:
    return "spoof" if "spoof" in path.relative_to(incoming).parts[:-1] else "bonafide"


def parse_name(stem: str) -> tuple:
    """file stem -> (speaker, phrase, round); `<speaker>__<phrase>_r<N>`, round 1 when there is no _r<N>."""
    speaker, sep, rest = stem.partition("__")
    if not sep:
        return stem, "", 1
    m = ROUND_RE.match(rest)
    return (speaker, m.group(1), int(m.group(2))) if m else (speaker, rest, 1)


def row_round(row: dict, fallback: int = 1) -> int:
    """Round of a manifest row: its `round` column, else the round in the file name, else 1."""
    try:
        return int(str(row.get("round") or "").strip())
    except ValueError:
        pass
    return parse_name(Path(row.get("file") or "").stem)[2] if row.get("file") else fallback


def read_incoming_manifest(incoming: Path) -> dict:
    """file (posix, relative to the session) -> metadata row, merged from every manifest*.csv
    (manifest.csv and older recorder pages' manifest_<station>.csv); {} if there is none.
    The first row seen for a (speaker_id, phrase_id, round) wins; extra columns are ignored."""
    out, seen = {}, set()
    for path in sorted(incoming.glob("manifest*.csv")):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                key = ((r.get("speaker_id") or "").strip(), (r.get("phrase_id") or "").strip(), row_round(r))
                if not r.get("file") or (all(key[:2]) and key in seen):
                    continue
                seen.add(key)
                out.setdefault(Path(r["file"]).as_posix(), r)
    return out


def consent_language(incoming: Path, speaker: str, cache: dict) -> str:
    """Fallback `language` from <speaker>.json (recorder consent metadata) next to the clips."""
    if speaker not in cache:
        lang = ""
        path = incoming / f"{speaker}.json"
        if ID_RE.match(speaker) and path.exists():
            try:
                lang = str(json.loads(path.read_text(encoding="utf-8")).get("metadata", {}).get("language") or "")
            except (OSError, ValueError, AttributeError):
                lang = ""
        cache[speaker] = lang
    return cache[speaker]


def recorder_entries(incoming: Path) -> list:
    """Entries of the folder-per-speaker layout (all bona fide, round 1; a redo overwrote the file)."""
    return [{"path": r["path"], "label": "bonafide", "round": 1, "consent_file": r["consent_file"],
             **{k: str(r[k]).strip() for k in ["speaker_id", "phrase_id", *META]}} for r in layout.scan_rows(incoming)]


def build_entries(incoming: Path) -> list:
    folders = layout.speaker_folders(incoming) if incoming.is_dir() else []
    out = recorder_entries(incoming) if folders else []
    meta = read_incoming_manifest(incoming)
    files = sorted(p for p in incoming.rglob("*") if p.is_file() and p.suffix.lower() in EXTS
                   and not any(f in p.parents for f in folders))
    langs = {}
    for p in files:
        rel = p.relative_to(incoming).as_posix()
        row = meta.get(rel) or meta.get(p.name) or {}
        spk, phr, rnd = parse_name(p.stem)
        e = {"path": p, "label": label_of(p, incoming),
             "speaker_id": (row.get("speaker_id") or spk).strip(),
             "phrase_id": (row.get("phrase_id") or phr).strip(),
             "round": row_round(row, rnd) if row else rnd,
             **{k: (row.get(k) or "").strip() for k in META}}
        if not e["language"]:
            e["language"] = consent_language(incoming, e["speaker_id"], langs).strip()
        out.append(e)
    return out


# -------------------------------------------------------------- consent
def consent_problem(speaker: str, label: str, consent_dir: Path, consent_file: Optional[Path] = None) -> Optional[str]:
    """Why this speaker's clip may not be ingested, or None when consent is fine.
    consent_file: the speaker folder's consent.json (recorder layout); otherwise <consent_dir>/<speaker>.json."""
    if not ID_RE.match(speaker):
        return f"bad speaker id '{speaker}'"
    rec = layout.load_consent(consent_file) if consent_file else get_consent(speaker, consent_dir)
    if rec is None:
        return "no consent record"
    if rec.speaker_id != speaker:
        return "consent record belongs to another speaker id"
    if not (rec.signed and rec.allow_recording):
        return "consent not signed or recording not allowed"
    if label == "spoof" and not rec.allow_spoof_testing:
        return "consent does not allow spoof testing"
    return None


def split_by_consent(entries: list, consent_dir: Path) -> tuple:
    ok, refused = [], defaultdict(set)
    for e in entries:
        why = consent_problem(e["speaker_id"], e["label"], consent_dir, e.get("consent_file"))
        if why:
            refused[(e["speaker_id"], e["label"], why)].add(e["path"].name)
        else:
            ok.append(e)
    return ok, refused


# ---------------------------------------------------------------- audio
def decode_16k(path: Path) -> np.ndarray:
    """Any container ffmpeg understands -> mono float32 at 16 kHz."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    proc = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
                           "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "ffmpeg failed")
    return np.frombuffer(proc.stdout, dtype="<f4").copy()


def trim_silence(x: np.ndarray) -> np.ndarray:
    """Cut leading/trailing frames quieter than TRIM_DB below the loudest frame, keep PAD_S around speech."""
    hop = int(0.02 * SR)
    n = len(x) // hop
    if n == 0:
        return x
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    loud = np.flatnonzero(rms > rms.max() * 10 ** (TRIM_DB / 20)) if rms.max() > 0 else []
    if len(loud) == 0:
        return x
    pad = int(PAD_S * SR)
    return x[max(0, loud[0] * hop - pad):min(len(x), (loud[-1] + 1) * hop + pad)]


def clean_clip(x: np.ndarray) -> tuple:
    """-> (int16 samples, None) or (None, reason)."""
    x = trim_silence(x)
    peak = float(np.abs(x).max()) if len(x) else 0.0
    if peak <= 0:
        return None, "silent"
    if len(x) / SR < MIN_S:
        return None, f"too short ({len(x) / SR:.2f} s)"
    return np.round(x / peak * PEAK * 32767).astype(np.int16), None


def write_pcm16(path: Path, pcm: np.ndarray) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), pcm, SR, subtype="PCM_16")


# --------------------------------------------------------------- ingest
def unique_utt(base: str, taken: set) -> str:
    utt, k = base, 1
    while utt in taken:
        k += 1
        utt = f"{base}-t{k}"
    return utt


def make_row(e: dict, utt: str, pcm: np.ndarray, sha1: str, known: dict) -> dict:
    """Manifest row; per-speaker metadata already in the manifest wins over the new drop."""
    prev = known.get(e["speaker_id"], {})
    row = {k: prev.get(k) or e[k] or UNKNOWN for k in META}
    row.update(utt_id=utt, speaker_id=e["speaker_id"], phrase_id=e["phrase_id"] or UNKNOWN,
               label=e["label"], duration_s=f"{len(pcm) / SR:.2f}", sha1=sha1, file=f"wav/{utt}.wav")
    return row


def ingest_entry(e: dict, out: Path, rows: list, known: dict) -> str:
    """Process one accepted entry; returns 'added', 'duplicate' or a rejection reason."""
    if not ID_RE.match(e["phrase_id"]):
        return "bad or missing phrase id"
    try:
        pcm, why = clean_clip(decode_16k(e["path"]))
    except RuntimeError as err:
        return f"decode failed: {err}"
    if pcm is None:
        return why
    sha1 = hashlib.sha1(pcm.tobytes()).hexdigest()
    if any(r["sha1"] == sha1 for r in rows):
        return "duplicate"
    tag = "sp" if e["label"] == "spoof" else "bf"
    rnd = f"_r{e['round']}" if e.get("round", 1) > 1 else ""  # round 1 keeps the plain utt id
    utt = unique_utt(f"{tag}__{e['speaker_id']}__{e['phrase_id']}{rnd}", {r["utt_id"] for r in rows})
    write_pcm16(out / "wav" / f"{utt}.wav", pcm)
    rows.append(make_row(e, utt, pcm, sha1, known))
    return "added"


def summarise(rows: list) -> str:
    per_spk = defaultdict(lambda: [0, 0, 0.0, UNKNOWN])
    for r in rows:
        s = per_spk[r["speaker_id"]]
        s[0 if r["label"] == "bonafide" else 1] += 1
        s[2] += float(r["duration_s"])
        s[3] = r["accent_group"]
    lines = ["speaker            accent          bonafide  spoof  minutes"]
    for spk, (b, sp, sec, acc) in sorted(per_spk.items()):
        lines.append(f"{spk:<18} {acc:<15} {b:>8} {sp:>6} {sec / 60:>8.1f}")
    per_acc = defaultdict(lambda: [set(), 0])
    for r in rows:
        per_acc[r["accent_group"]][0].add(r["speaker_id"])
        per_acc[r["accent_group"]][1] += r["label"] == "bonafide"
    lines.append("")
    lines.append("accent group       speakers  bonafide clips")
    for acc, (spks, n) in sorted(per_acc.items()):
        lines.append(f"{acc:<18} {len(spks):>8} {n:>15}")
    lines.append(f"total: {len(per_spk)} speakers, {len(rows)} clips")
    return "\n".join(lines)


def run(incoming: Path, out: Path, consent_dir: Path) -> int:
    entries = build_entries(incoming)
    if not entries:
        print(f"error: no audio files ({', '.join(sorted(EXTS))}) under {incoming}", file=sys.stderr)
        return 2
    accepted, refused = split_by_consent(entries, consent_dir)
    for (spk, label, why), names in sorted(refused.items()):
        print(f"REFUSED {spk} ({label}, {len(names)} files): {why}", file=sys.stderr)
    rows = read_manifest(out / "manifest.csv")
    known = {r["speaker_id"]: r for r in rows}
    tally = defaultdict(int)
    for e in accepted:
        result = ingest_entry(e, out, rows, known)
        tally[result.split(" (")[0]] += 1
        if result not in ("added", "duplicate"):
            print(f"rejected {e['path'].name}: {result}", file=sys.stderr)
    write_manifest(out / "manifest.csv", rows)
    print(f"added {tally['added']}, duplicates {tally['duplicate']}, "
          f"rejected {sum(tally.values()) - tally['added'] - tally['duplicate']}, "
          f"refused (no consent) {sum(len(v) for v in refused.values())}")
    print(summarise(rows))
    return 1 if refused else 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incoming", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--consent-dir", type=Path, default=ROOT / CONSENT_DIR)
    a = ap.parse_args(argv)
    return run(a.incoming, a.out, a.consent_dir)


if __name__ == "__main__":
    sys.exit(main())
