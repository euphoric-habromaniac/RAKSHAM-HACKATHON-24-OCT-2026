"""Shared file formats for the Hinglish set (manifest.csv, splits.json).

Layout under data/hinglish/:
    wav/<utt_id>.wav     16 kHz mono 16-bit, bona fide and spoof side by side
    manifest.csv         one row per clip (MANIFEST_FIELDS)
    splits.json          {"speakers": {speaker_id: "train"|"val"|"heldout"}, ...}
    protocols/*.txt      ASVspoof-LA-style protocol per split
    deg/<cond>/          degraded copies of wav/ (degrade.telephony)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DIR = ROOT / "data" / "hinglish"
MANIFEST_FIELDS = ["utt_id", "speaker_id", "phrase_id", "label", "language", "accent_group",
                   "age_band", "gender", "device", "duration_s", "sha1", "file"]
SPLIT_NAMES = ("train", "val", "heldout")
UNKNOWN = "unknown"


def read_manifest(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["utt_id"]))
    tmp.replace(path)


def speaker_accents(rows: list) -> dict:
    """speaker_id -> accent_group (first non-unknown value seen, else 'unknown')."""
    out = {}
    for r in rows:
        acc = r.get("accent_group") or UNKNOWN
        if out.get(r["speaker_id"], UNKNOWN) == UNKNOWN:
            out[r["speaker_id"]] = acc
    return out


def load_splits(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rows_in_split(rows: list, splits: dict, split: str) -> list:
    spk = splits["speakers"]
    return [r for r in rows if spk.get(r["speaker_id"]) == split]
