"""Score base and fine-tuned AASIST weights on the same trials and write a comparison table.

    python -m eval.compare_models --weights base=C:\\...\\AASIST.pth --weights ftB=C:\\...\\aasist_ftB.pth \\
        --hinglish-dir data/hinglish --out results_ft

Per model label, one CSV per condition (same schema as eval.run_aasist, incl.
spoof_logit):
    results_ft/<label>/<cond>.csv             LA eval subset (same protocol, --limit, --seed, --balanced as the baseline)
    results_ft/<label>/hinglish/<cond>.csv    Hinglish held-out speakers (data/hinglish/protocols/heldout.txt)
then results_ft/COMPARE.md. Models are scored ONE AT A TIME under the GPU lock;
existing CSVs are reused (use --overwrite to redo). --report-only rebuilds the
table from CSVs without touching a model or the GPU.

If the Hinglish held-out set has no spoof clips (no clones), its EER uses the
LA eval spoofs of the same condition as the spoof side; the table marks this with *.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402
from eval.gpu_lock import LockHeld, gpu_lock  # noqa: E402
from eval.run_aasist import find_audio, read_protocol, subset, write_scores  # noqa: E402
from eval.summarise import ORDER  # noqa: E402
from tools.hinglish_data import read_manifest  # noqa: E402

LA_PROTOCOL = ROOT / "data/raw/LA/ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.eval.trl.txt"
ACCENT_CONDS = ("clean16k", "gsm", "noise10")
NOTE = ("Uncertainty: no confidence intervals are computed. Held-out Hinglish clips come from few speakers "
        "and clips of one speaker are correlated, so treat differences of a few points as noise. The same "
        "clip degraded 11 ways is not 11 independent samples. Channels are simulated; EER is on one "
        "model. '*' = spoof side borrowed from the LA eval subset (Hinglish has no spoof clips).")


# --------------------------------------------------------------- scoring
def cond_dir(cond: str, clean_dir: Path, deg_root: Path) -> Path:
    return clean_dir if cond == "clean16k" else deg_root / cond


def score_trials(model, items: list, audio_dir: Path, out_csv: Path, device, batch_size: int) -> bool:
    """Score (utt, label) trials found in audio_dir and write out_csv. False if audio is missing."""
    from eval.run_aasist import score_files
    found = [(u, l, find_audio(audio_dir, u)) for u, l in items]
    if any(p is None for _, _, p in found):
        print(f"skip {out_csv.name}: {sum(p is None for _, _, p in found)} files missing in {audio_dir}")
        return False
    scores, spoof = score_files(model, [p for _, _, p in found], device, batch_size, 0, return_spoof=True)
    write_scores(out_csv, [(u, l, s, sp) for (u, l, _), s, sp in zip(found, scores, spoof)])
    return True


def score_model(label: str, weights: Path, a, la_items: list, hg_items: list, conds: list) -> None:
    import torch
    from eval.run_aasist import load_model
    device = torch.device(a.device)
    model = load_model(a.aasist_repo, a.model, device, weights.resolve())
    for cond in conds:
        jobs = [(la_items, cond_dir(cond, a.la_clean_dir, a.la_deg_root), a.out / label / f"{cond}.csv"),
                (hg_items, cond_dir(cond, a.hinglish_dir / "wav", a.hinglish_dir / "deg"),
                 a.out / label / "hinglish" / f"{cond}.csv")]
        for items, adir, out_csv in jobs:
            if items and (a.overwrite or not out_csv.exists()):
                print(f"[{label}] {cond} -> {out_csv}")
                score_trials(model, items, adir, out_csv, device, a.batch_size)
    del model
    if device.type == "cuda":
        torch.cuda.empty_cache()


# ----------------------------------------------------------------- report
def read_scores(path: Path) -> list:
    """-> [(utt_id, label 1/0, score)] or []"""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [(r["utt_id"], 1 if r["label"] == "bonafide" else 0, float(r["score"]))
                for r in csv.DictReader(f)]


def eer_text(bona: list, spoof: list, star: bool = False) -> str:
    if not bona or not spoof:
        return "n/a"
    return f"{compute_eer(bona, spoof)[0] * 100:.2f}{'*' if star else ''} ({len(bona)}/{len(spoof)})"


def split_scores(rows: list) -> tuple:
    return [s for _, l, s in rows if l == 1], [s for _, l, s in rows if l == 0]


def hinglish_scores(out: Path, label: str, cond: str, utt_filter=None) -> tuple:
    """-> (bonafide scores, spoof scores, borrowed_spoof). utt_filter selects Hinglish utterances."""
    rows = read_scores(out / label / "hinglish" / f"{cond}.csv")
    if utt_filter:
        rows = [r for r in rows if utt_filter(r[0])]
    bona, spoof = split_scores(rows)
    if bona and not spoof:
        return bona, split_scores(read_scores(out / label / f"{cond}.csv"))[1], True
    return bona, spoof, False


def hinglish_cell(out: Path, label: str, cond: str, utt_filter=None) -> str:
    bona, spoof, borrowed = hinglish_scores(out, label, cond, utt_filter)
    return eer_text(bona, spoof, star=borrowed)


def ordered(conds) -> list:
    return [c for c in ORDER if c in conds] + sorted(c for c in conds if c not in ORDER)


def found_conds(out: Path, labels: list, sub: str = "") -> list:
    names = {p.stem for lab in labels for p in (out / lab / sub).glob("*.csv")}
    return ordered(names)


def la_table(out: Path, labels: list) -> list:
    lines = ["## LA eval subset (simulated channels), EER % (n bona fide / n spoof)", "",
             "| Condition | " + " | ".join(labels) + " | change last vs first (points) |",
             "|---|" + "---:|" * (len(labels) + 1)]
    for cond in found_conds(out, labels):
        cells, vals = [], []
        for lab in labels:
            bona, spoof = split_scores(read_scores(out / lab / f"{cond}.csv"))
            cells.append(eer_text(bona, spoof))
            vals.append(compute_eer(bona, spoof)[0] * 100 if bona and spoof else None)
        delta = f"{vals[-1] - vals[0]:+.2f}" if len(vals) > 1 and None not in (vals[0], vals[-1]) else ""
        lines.append(f"| {cond} | " + " | ".join(cells) + f" | {delta} |")
    return lines


def hinglish_table(out: Path, labels: list) -> list:
    lines = ["## Hinglish held-out speakers, EER % (n bona fide / n spoof)", "",
             "| Condition | " + " | ".join(labels) + " |", "|---|" + "---:|" * len(labels)]
    for cond in found_conds(out, labels, "hinglish"):
        cells = [hinglish_cell(out, lab, cond) for lab in labels]
        lines.append(f"| {cond} | " + " | ".join(cells) + " |")
    return lines


def accent_tables(out: Path, labels: list, hinglish: Path, min_n: int) -> list:
    rows = read_manifest(hinglish / "manifest.csv")
    utt_accent = {r["utt_id"]: r["accent_group"] for r in rows}
    utt_spk = {r["utt_id"]: r["speaker_id"] for r in rows}
    accents = sorted({utt_accent[u] for u, _, _ in read_scores(out / labels[0] / "hinglish" / "clean16k.csv")
                      if u in utt_accent})
    lines = [f"## Per accent group (held-out speakers), EER %; groups with fewer than {min_n} bona fide clips are not scored", ""]
    for cond in [c for c in ACCENT_CONDS if c in found_conds(out, labels, "hinglish")]:
        lines += [f"### {cond}", "", "| Accent group | speakers | " + " | ".join(labels) + " |",
                  "|---|---:|" + "---:|" * len(labels)]
        for acc in accents:
            def sel(u, acc=acc):
                return utt_accent.get(u) == acc
            bona0 = hinglish_scores(out, labels[0], cond, sel)[0]
            n_spk = len({utt_spk[u] for u, l, _ in read_scores(out / labels[0] / "hinglish" / f"{cond}.csv")
                         if sel(u) and l == 1})
            cells = ["n<%d" % min_n if len(bona0) < min_n else
                     hinglish_cell(out, lab, cond, sel)
                     for lab in labels]
            lines.append(f"| {acc} | {n_spk} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def build_report(out: Path, labels: list, hinglish: Path, min_n: int = 20) -> str:
    lines = ["# Model comparison: " + " vs ".join(labels), "", NOTE, ""]
    lines += la_table(out, labels) + [""]
    if found_conds(out, labels, "hinglish"):
        lines += hinglish_table(out, labels) + [""]
        lines += accent_tables(out, labels, hinglish, min_n)
    else:
        lines += ["(no Hinglish held-out scores found)", ""]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------- CLI
def parse_weights(specs: list, ap) -> dict:
    out = {}
    for s in specs:
        label, _, path = s.partition("=")
        if not path:
            ap.error(f"--weights expects LABEL=PATH, got '{s}'")
        out[label] = Path(path)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", action="append", default=[], metavar="LABEL=PATH",
                    help="repeatable, absolute paths; first is the base")
    ap.add_argument("--aasist-repo", type=Path, default=ROOT / "aasist")
    ap.add_argument("--model", choices=["AASIST", "AASIST-L"], default="AASIST")
    ap.add_argument("--la-protocol", type=Path, default=LA_PROTOCOL)
    ap.add_argument("--la-clean-dir", type=Path, default=ROOT / "data/raw/LA/subset5000/flac")
    ap.add_argument("--la-deg-root", type=Path, default=ROOT / "data/deg")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--hinglish-dir", type=Path, default=ROOT / "data/hinglish")
    ap.add_argument("--conds", default=",".join(ORDER))
    ap.add_argument("--out", type=Path, default=ROOT / "results_ft")
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--min-n", type=int, default=20, help="min bona fide clips to score an accent group")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    return ap


def heldout_items(hinglish: Path) -> list:
    p = hinglish / "protocols" / "heldout.txt"
    return read_protocol(p) if p.exists() else []


def score_all(a, models: dict) -> None:
    la_items = subset(read_protocol(a.la_protocol), a.limit, a.seed, balanced=True)
    hg_items = heldout_items(a.hinglish_dir)
    if not hg_items:
        print("note: no Hinglish held-out protocol; scoring LA only")
    conds = [c for c in a.conds.split(",") if c]
    for label, weights in models.items():  # strictly one model after another
        score_model(label, weights, a, la_items, hg_items, conds)


def main(argv: Optional[list] = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    models = parse_weights(a.weights, ap)
    if not models and not a.report_only:
        ap.error("give at least one --weights LABEL=PATH (or --report-only)")
    labels = list(models) or sorted(p.name for p in a.out.iterdir() if p.is_dir())
    if not a.report_only:
        try:
            if a.device == "cpu":
                score_all(a, models)
            else:
                with gpu_lock():
                    score_all(a, models)
        except LockHeld as e:
            print(f"error: {e}", file=sys.stderr)
            return 3
    report = a.out / "COMPARE.md"
    report.write_text(build_report(a.out, labels, a.hinglish_dir, a.min_n), encoding="utf-8")
    print(f"wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
