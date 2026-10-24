"""Write ASVspoof-LA-style protocol files for the Hinglish splits.

    python -m tools.make_hinglish_protocol --hinglish data/hinglish
    python -m tools.make_hinglish_protocol --hinglish data/hinglish --degrade g711u,gsm,noise10 --workers 4

Writes data/hinglish/protocols/{train,val,heldout}.txt, one line per clip:
    <speaker_id> <utt_id> - <HGCLONE|-> <bonafide|spoof>
eval.run_aasist.read_protocol uses column 2 and the last column, so these work
unchanged with the flat audio dir data/hinglish/wav, e.g.
    python -m eval.run_aasist --aasist-repo aasist --protocol data/hinglish/protocols/heldout.txt \
        --audio-dir data/hinglish/wav --weights <abs path> --device cuda --out results_ft/x.csv
--degrade runs the existing degrade.telephony over wav/ into data/hinglish/deg/<cond>/
(same file names, so the same protocol works with --audio-dir data/hinglish/deg/<cond>).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hinglish_data import (DEFAULT_DIR, SPLIT_NAMES, load_splits, read_manifest,  # noqa: E402
                                 rows_in_split)


def protocol_line(row: dict) -> str:
    attack = "HGCLONE" if row["label"] == "spoof" else "-"
    return f"{row['speaker_id']} {row['utt_id']} - {attack} {row['label']}"


def write_protocols(hinglish: Path) -> dict:
    """Write one protocol per non-empty split; returns {split: n_lines}."""
    rows = read_manifest(hinglish / "manifest.csv")
    splits = load_splits(hinglish / "splits.json")
    counts = {}
    for name in SPLIT_NAMES:
        part = sorted(rows_in_split(rows, splits, name), key=lambda r: r["utt_id"])
        if not part:
            continue
        out = hinglish / "protocols" / f"{name}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(protocol_line(r) for r in part) + "\n", encoding="utf-8")
        counts[name] = len(part)
    return counts


def degrade_hinglish(hinglish: Path, conditions: list, workers: int = 1) -> None:
    from degrade.telephony import degrade_dir
    for cond in conditions:
        degrade_dir(hinglish / "wav", hinglish / "deg" / cond, cond, workers)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hinglish", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--degrade", default="", help="comma-separated degrade.telephony conditions, e.g. g711u,gsm")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)

    if not (a.hinglish / "splits.json").exists():
        print("error: run tools.split_hinglish first", file=sys.stderr)
        return 2
    counts = write_protocols(a.hinglish)
    for name, n in counts.items():
        print(f"{a.hinglish / 'protocols' / (name + '.txt')}: {n} clips")
    conds = [c for c in a.degrade.split(",") if c]
    if conds:
        from degrade.telephony import DegradeError
        try:
            degrade_hinglish(a.hinglish, conds, a.workers)
        except DegradeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
