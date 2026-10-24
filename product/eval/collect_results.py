"""Collect measured numbers for the deck's open placeholders into results.json.

Two inputs, both optional but at least one is needed:

1. A directory of consented Hinglish recordings plus a manifest CSV.
   Manifest columns (header row required):
       file         path relative to the recordings dir
       speaker_id   any stable id, one per person
       consent      yes / true / 1 when written consent is on file
       duration_sec optional; WAV files are measured directly, other formats
                    need this column or their minutes are reported as unknown
   Only rows that have consent, a speaker id and an existing file are counted.
   Everything else is listed under "rejected" with the reason.

2. The results folder written by eval.run_aasist (one CSV per condition).
   EER is recomputed from the score files with eval.eer.compute_eer.

Usage:
    python -m eval.collect_results --recordings DIR --manifest manifest.csv \
        --baseline-results results --out results.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import wave
from collections import Counter
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402
from eval.summarise import load_scores  # noqa: E402

YES = {"yes", "y", "true", "1", "consented"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wav_seconds(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (wave.Error, EOFError, OSError):
        return None


def collect_recordings(rec_dir: Path, manifest: Path) -> dict:
    accepted, rejected = [], []
    seen = set()
    with open(manifest, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"file", "speaker_id", "consent"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"manifest lacks columns: {sorted(missing)}")
        for i, row in enumerate(reader, start=2):
            name = (row.get("file") or "").strip()
            spk = (row.get("speaker_id") or "").strip()
            why = None
            if not name:
                why = "no file name"
            elif name in seen:
                why = "duplicate row"
            elif not spk:
                why = "no speaker_id"
            elif (row.get("consent") or "").strip().lower() not in YES:
                why = "no consent recorded"
            elif not (rec_dir / name).is_file():
                why = "file not found in recordings dir"
            if why:
                rejected.append({"row": i, "file": name, "reason": why})
                continue
            seen.add(name)
            secs = wav_seconds(rec_dir / name)
            if secs is None:
                try:
                    secs = float(row.get("duration_sec") or "")
                except ValueError:
                    secs = None
            accepted.append((name, spk, secs))
    per_spk = Counter(s for _, s, _ in accepted)
    unknown = sum(1 for _, _, d in accepted if d is None)
    known = [d for _, _, d in accepted if d is not None]
    counts = sorted(per_spk.values())
    return {
        "n_speakers": len(per_spk),
        "n_clips": len(accepted),
        "clips_per_speaker": {
            "min": counts[0] if counts else 0,
            "max": counts[-1] if counts else 0,
            "uniform": bool(counts) and counts[0] == counts[-1],
        },
        "total_minutes": round(sum(known) / 60, 2) if unknown == 0 and accepted else None,
        "clips_with_unknown_duration": unknown,
        "n_rejected": len(rejected),
        "rejected": rejected,
        "manifest": {"file": str(manifest), "sha256": sha256(manifest)},
    }


def collect_baseline(results_dir: Path) -> dict:
    out = {}
    for p in sorted(results_dir.glob("*.csv")):
        bona, spoof = load_scores(p)
        if not bona or not spoof:
            continue
        eer, _ = compute_eer(bona, spoof)
        out[p.stem] = {"n_bonafide": len(bona), "n_spoof": len(spoof),
                       "eer_percent": round(eer * 100, 4),
                       "source": {"file": str(p), "sha256": sha256(p)}}
    if not out:
        raise SystemExit(f"no usable score CSVs in {results_dir}")
    return out


def build(recordings: Optional[Path], manifest: Optional[Path],
          baseline: Optional[Path], command: str) -> dict:
    if (recordings is None) != (manifest is None):
        raise SystemExit("--recordings and --manifest go together")
    if recordings is None and baseline is None:
        raise SystemExit("give --recordings/--manifest, --baseline-results, or both")
    res = {"provenance": {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "script": "eval/collect_results.py",
    }}
    if recordings is not None:
        res["hinglish_set"] = collect_recordings(recordings, manifest)
        res["hinglish_set"]["recordings_dir"] = str(recordings)
    if baseline is not None:
        res["baseline_eer"] = collect_baseline(baseline)
    return res


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--recordings", type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--baseline-results", type=Path)
    ap.add_argument("--out", type=Path, default=Path("results.json"))
    a = ap.parse_args(argv)
    command = " ".join(["python", "-m", "eval.collect_results"] + (argv if argv is not None else sys.argv[1:]))
    res = build(a.recordings, a.manifest, a.baseline_results, command)
    a.out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    h = res.get("hinglish_set")
    if h:
        print(f"Hinglish set: {h['n_speakers']} speakers, {h['n_clips']} clips, "
              f"minutes={h['total_minutes']}, rejected={h['n_rejected']}")
    for k, v in res.get("baseline_eer", {}).items():
        print(f"{k}: EER {v['eer_percent']:.2f}% (n={v['n_bonafide'] + v['n_spoof']})")
    print(f"written to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
