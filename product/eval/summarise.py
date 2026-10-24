"""Collect results/*.csv into a markdown table (results/SUMMARY.md).

Each CSV is written by eval.run_aasist (columns utt_id,label,score); the
condition name is the file name without extension.

Usage: python -m eval.summarise [--results results] [--model-label AASIST]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402

ORDER = ["clean16k", "pstn8k", "g711u", "g711a", "gsm", "amrnb", "opus8k",
         "loss5", "loss10", "noise20", "noise10"]


def load_scores(path: Path) -> tuple:
    bona, spoof = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            (bona if row["label"] == "bonafide" else spoof).append(float(row["score"]))
    return bona, spoof


def summarise(results_dir: Path, model_label: str = "AASIST") -> str:
    rows = {}
    for p in sorted(results_dir.glob("*.csv")):
        bona, spoof = load_scores(p)
        if not bona or not spoof:
            print(f"warning: {p.name} lacks one class, skipped", file=sys.stderr)
            continue
        eer, _ = compute_eer(bona, spoof)
        rows[p.stem] = (len(bona), len(spoof), eer * 100)
    if not rows:
        raise SystemExit(f"no usable CSVs in {results_dir}")
    names = [n for n in ORDER if n in rows] + sorted(n for n in rows if n not in ORDER)
    base = rows.get("clean16k", (None, None, None))[2]
    lines = [
        f"# Baseline results: {model_label} on ASVspoof 2019 LA eval",
        "",
        "These are pretrained-model results without fine-tuning: the released "
        f"{model_label} weights were scored as they are on clean and telephone-degraded audio.",
        "",
        "| Condition | n_bonafide | n_spoof | EER % | Change vs clean16k (points) |",
        "|---|---:|---:|---:|---:|",
    ]
    for n in names:
        nb, ns, e = rows[n]
        delta = "" if base is None or n == "clean16k" else f"{e - base:+.2f}"
        lines.append(f"| {n} | {nb} | {ns} | {e:.2f} | {delta} |")
    counts = {(r[0], r[1]) for r in rows.values()}
    if len(counts) > 1:
        lines += ["", "Note: conditions do not have the same number of trials, so the rows are not "
                      "strictly comparable. Rerun with the same --limit/--seed and no missing files."]
    return "\n".join(lines) + "\n"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=Path("results"))
    ap.add_argument("--model-label", default="AASIST")
    a = ap.parse_args(argv)
    text = summarise(a.results, a.model_label)
    out = a.results / "SUMMARY.md"
    out.write_text(text)
    print(text)
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
