"""Consent and audio gate for incoming Hinglish recordings (HUMAN_TODO H1).

Checks every clip of a recordings folder (--incoming, the layout of tools/recorder) or every row of one or
more manifest_<station>.csv files (--manifest, older flat sessions):
  * the speaker has a signed consent record allowing recording (and, if asked, spoof testing / cloning)
  * the clip exists and is a 16 kHz mono 16-bit WAV of sane length
  * no duplicate (speaker_id, phrase_id, round) or file rows (extra manifest columns are ignored;
    the round is the `round` column or the _r<N> in the file name, 1 for old names)

Usage (from the repo root):
    python tools/verify_consent.py --incoming downloads/recordings_awaaz
        (folder per speaker: N.wav, profile.json, consent.json; the speaker id and consent come from those files)
    # older flat sessions:
    python tools/verify_consent.py --manifest data/hinglish_incoming/s1/manifest_spk01.csv \
        --consent-dir data/consent --audio-dir data/hinglish_incoming/s1
Exit code 0 only if every row passes.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from service.consent import get_consent  # noqa: E402
from tools.recorder import layout  # noqa: E402

REQUIRED_COLUMNS = ["speaker_id", "phrase_id", "language", "accent_group", "age_band",
                    "gender", "device", "duration_s", "file"]
SAMPLE_RATE = 16000
ROUND_IN_NAME = re.compile(r"_r(\d+)$")
NON_WAV_EXTS = {".mp3", ".m4a", ".webm", ".flac", ".ogg", ".aac"}


def load_rows(manifests: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for m in manifests:
        with open(m, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise SystemExit(f"{m}: missing manifest columns {missing}")
            rows.extend(reader)
    return rows


def consent_error(speaker_id: str, consent_dir: Path, need_spoof: bool, need_clone: bool, consent_file: Path | None = None) -> str:
    """Empty string if the speaker's consent record covers everything required.
    consent_file: a speaker folder's consent.json (recorder layout); otherwise <consent_dir>/<speaker_id>.json."""
    rec = layout.load_consent(consent_file) if consent_file else get_consent(speaker_id, consent_dir)
    if rec is None:
        return "no consent record"
    if rec.speaker_id != speaker_id:
        return "consent record belongs to another speaker id"
    if not rec.signed:
        return "consent not signed"
    if not rec.allow_recording:
        return "recording not allowed"
    if need_spoof and not rec.allow_spoof_testing:
        return "spoof testing not allowed"
    if need_clone and not rec.allow_voice_cloning:
        return "voice cloning not allowed"
    return ""


def audio_error(path: Path, min_s: float, max_s: float) -> str:
    """Empty string if path is a 16 kHz mono 16-bit WAV with duration in [min_s, max_s]."""
    if not path.exists():
        return "file missing"
    convert = "; run ingest to convert (python -m tools.ingest_hinglish)"
    if path.suffix.lower() in NON_WAV_EXTS:
        return f"{path.suffix.lower()} is not a 16 kHz mono PCM16 WAV{convert}"
    try:
        info = sf.info(str(path))
    except Exception as exc:  # unreadable or not audio
        return f"unreadable audio ({type(exc).__name__}){convert}"
    if info.format != "WAV" or info.subtype != "PCM_16":
        return f"not 16-bit WAV ({info.format}/{info.subtype}){convert}"
    if info.samplerate != SAMPLE_RATE:
        return f"sample rate {info.samplerate} != {SAMPLE_RATE}{convert}"
    if info.channels != 1:
        return f"{info.channels} channels, need mono{convert}"
    if not min_s <= info.duration <= max_s:
        return f"duration {info.duration:.2f}s outside [{min_s}, {max_s}]"
    return ""


def row_round(r: dict) -> str:
    """Round of a manifest row: the `round` column, else _r<N> in the file name, else '1'."""
    value = (r.get("round") or "").strip()
    if value:
        return value
    m = ROUND_IN_NAME.search(Path(r["file"]).stem)
    return m.group(1) if m else "1"


def duplicate_keys(rows: list[dict]) -> set[tuple]:
    """Keys ('id', speaker, phrase, round) or ('file', name) that occur more than once."""
    counts = Counter()
    for r in rows:
        counts[("id", r["speaker_id"], r["phrase_id"], row_round(r))] += 1
        counts[("file", r["file"])] += 1
    return {k for k, n in counts.items() if n > 1}


def check_rows(rows: list[dict], args: argparse.Namespace) -> list[tuple[dict, str]]:
    """One (row, error) pair per row; error is '' on pass."""
    dups = duplicate_keys(rows)
    consent_cache: dict = {}
    results = []
    for r in rows:
        sid, cfile = r["speaker_id"], r.get("consent_file")
        if (sid, cfile) not in consent_cache:
            consent_cache[(sid, cfile)] = consent_error(sid, args.consent_dir, args.allow_spoof_testing, args.allow_cloning, cfile)
        err = consent_cache[(sid, cfile)]
        if not err and (("id", sid, r["phrase_id"], row_round(r)) in dups or ("file", r["file"]) in dups):
            err = "duplicate row"
        if not err:
            err = audio_error(args.audio_dir / r["file"], args.min_seconds, args.max_seconds)
        results.append((r, err))
    return results


def print_report(results: list[tuple[dict, str]]) -> None:
    print(f"{'STATUS':<6} {'SPEAKER':<14} {'FILE':<34} REASON")
    for r, err in results:
        print(f"{'FAIL' if err else 'PASS':<6} {r['speaker_id']:<14} {r['file']:<34} {err}")
    speakers = sorted({r["speaker_id"] for r, _ in results})
    print("\nPer speaker:")
    for s in speakers:
        mine = [err for r, err in results if r["speaker_id"] == s]
        bad = sum(1 for e in mine if e)
        print(f"  {'FAIL' if bad else 'PASS':<6} {s:<14} {len(mine) - bad}/{len(mine)} clips ok")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incoming", type=Path, help="recordings folder: <Speaker Name>/N.wav + profile.json + consent.json")
    ap.add_argument("--manifest", type=Path, nargs="+", help="one or more manifest_<station>.csv files (older flat sessions)")
    ap.add_argument("--consent-dir", type=Path, default=Path("data/consent"))
    ap.add_argument("--audio-dir", type=Path, help="folder the manifest 'file' column is relative to (default with --incoming: that folder)")
    ap.add_argument("--allow-spoof-testing", action="store_true", help="also require allow_spoof_testing")
    ap.add_argument("--allow-cloning", action="store_true", help="also require allow_voice_cloning")
    ap.add_argument("--min-seconds", type=float, default=1.0)
    ap.add_argument("--max-seconds", type=float, default=15.0)
    args = ap.parse_args(argv)
    if args.incoming:
        args.audio_dir = args.audio_dir or args.incoming
    elif not (args.manifest and args.audio_dir):
        ap.error("give --incoming <recordings folder>, or --manifest ... together with --audio-dir")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = layout.scan_rows(args.incoming) if args.incoming else load_rows(args.manifest)
    if not rows:
        print("FAIL: no clips found (manifest has no rows, or no speaker folder has N.wav files)")
        return 1
    results = check_rows(rows, args)
    print_report(results)
    failed = sum(1 for _, err in results if err)
    print(f"\n{'FAIL' if failed else 'PASS'}: {len(results) - failed}/{len(results)} clips ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
