"""Fit L2 Platt calibration and band thresholds from measured AASIST scores.

Usage (repo root):
    python -m eval.fit_calibration --results results --out service/config.calibrated.json \
        --report results/CALIBRATION.md --seed 0

Score mapping (exact): the result CSVs hold the bona fide logit (`score`) and the `spoof_logit`
column written by eval.run_aasist. The raw L2 input is computed with the SAME function the service
uses, service.scorers.spoof_probability([spoof_logit, bonafide_logit]) = sigmoid(spoof - bonafide),
and p = sigmoid(a*x + b) is fitted with label 1 = spoof, so a, b drop into config.json unchanged.
CSVs without a spoof_logit column are rejected: rerun eval.run_aasist.

Split: utterances (not rows) are split 50/50, seeded, stratified by label; an utterance is in
the same split for every condition. Platt and the operative (pooled) thresholds are fitted on the
pooled FIT split over all conditions. Per-condition thresholds (same genuine targets, fit split
per condition, same pooled Platt) are reported alongside but are NOT used by the service config.
All reported results come from the HELD-OUT split only.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402
from service.scorers import spoof_probability  # noqa: E402

STEPUP_TARGET_DEFAULT = 5.0  # percent of genuine, eval/targets.json genuine_stepup_target_pct
WEAK_TARGET_DEFAULT = 10.0   # percent of genuine allowed at/above the weak threshold (our choice)
SCORE_MAPPING = ("x = service.scorers.spoof_probability([spoof_logit, bonafide_logit]) "
                 "= sigmoid(spoof_logit - bonafide_logit), exactly the service's raw L2 input")


def sigmoid(z):
    z = np.asarray(z, dtype=np.float64)
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    e = np.exp(z[~pos])
    out[~pos] = e / (1.0 + e)
    return out


def service_input(spoof_logit, bonafide_logit) -> np.ndarray:
    """Raw L2 input exactly as the service computes it, row by row."""
    return np.array([spoof_probability([sp, bf]) for sp, bf in zip(spoof_logit, bonafide_logit)])


# ------------------------------------------------------------------ data
def load_results(results_dir: Path, conditions: Optional[List[str]] = None) -> Dict[str, dict]:
    """{condition: {'ids', 'label' (1=spoof), 'bf' (bonafide logit), 'x' (service raw L2 input)}}."""
    results_dir = Path(results_dir)
    files = sorted(results_dir.glob("*.csv"))
    if conditions:
        files = [f for f in files if f.stem in conditions]
    if not files:
        raise ValueError(f"no result CSVs in {results_dir}")
    out = {}
    for f in files:
        ids, lab, sc, sl = [], [], [], []
        with open(f, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if "spoof_logit" not in (reader.fieldnames or []):
                raise ValueError(f"{f.name} has no spoof_logit column; rerun eval.run_aasist to rescore")
            for row in reader:
                ids.append(row["utt_id"])
                lab.append(1 if row["label"].strip().lower() == "spoof" else 0)
                sc.append(float(row["score"]))
                sl.append(float(row["spoof_logit"]))
        bf = np.asarray(sc)
        out[f.stem] = {"ids": ids, "label": np.asarray(lab), "bf": bf, "x": service_input(sl, bf),
                       "file": f.name}
    return out


def split_ids(data: Dict[str, dict], seed: int = 0, fit_frac: float = 0.5) -> Tuple[set, set]:
    """Deterministic label-stratified split of utterance ids (union over conditions)."""
    labels: Dict[str, int] = {}
    for d in data.values():
        for u, y in zip(d["ids"], d["label"]):
            if labels.setdefault(u, int(y)) != int(y):
                raise ValueError(f"utterance {u} has inconsistent labels across conditions")
    fit, held = set(), set()
    for y in (0, 1):
        ids = sorted(u for u, l in labels.items() if l == y)
        random.Random(seed * 2 + y).shuffle(ids)
        k = int(round(len(ids) * fit_frac))
        fit.update(ids[:k])
        held.update(ids[k:])
    return fit, held


def pool(data: Dict[str, dict], ids: set, conds=None):
    xs, ys = [], []
    for c, d in data.items():
        if conds and c not in conds:
            continue
        m = np.array([u in ids for u in d["ids"]])
        xs.append(d["x"][m])
        ys.append(d["label"][m])
    return np.concatenate(xs), np.concatenate(ys)


# ------------------------------------------------------------------ fit
def fit_platt_np(x, y, ridge: float = 1e-9, iters: int = 100) -> Tuple[float, float]:
    """Logistic regression p = sigmoid(a*x + b) by Newton/IRLS. y: 1 = positive (spoof)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    X = np.stack([x, np.ones_like(x)], axis=1)
    w = np.zeros(2)
    for _ in range(iters):
        p = sigmoid(X @ w)
        g = X.T @ (p - y) + ridge * w
        W = p * (1 - p)
        H = (X * W[:, None]).T @ X + ridge * np.eye(2)
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(w[0]), float(w[1])


def _between_top_k(p_desc: np.ndarray, k: int) -> float:
    """Threshold t such that exactly the top-k values are >= t (ties permitting)."""
    n = len(p_desc)
    if k <= 0:
        return float(min(np.nextafter(p_desc[0], 1.0), 1.0 - 1e-12))
    if k >= n:
        return float(p_desc[-1])
    hi, lo = p_desc[k - 1], p_desc[k]
    t = (hi + lo) / 2.0
    if t <= lo:  # tie: strictly above the tied value so the rate stays within target
        t = float(np.nextafter(lo, 1.0))
    return float(t)


def choose_thresholds(p_genuine, stepup_pct: float = STEPUP_TARGET_DEFAULT,
                      weak_pct: float = WEAK_TARGET_DEFAULT) -> Tuple[float, float]:
    """(weak, strong) on calibrated probability from GENUINE (fit-split) probabilities.

    strong: at most stepup_pct % of genuine calls at/above it (one strong signal => Step up).
    weak: at most weak_pct % of genuine at/above it (two weak signals => Step up).
    """
    p = np.sort(np.asarray(p_genuine, dtype=np.float64))[::-1]
    if len(p) == 0:
        raise ValueError("no genuine samples")
    strong = _between_top_k(p, int(np.floor(len(p) * stepup_pct / 100.0)))
    weak = _between_top_k(p, int(np.floor(len(p) * max(weak_pct, stepup_pct) / 100.0)))
    eps = 1e-9
    strong = min(max(strong, 2 * eps), 1 - eps)
    weak = min(max(weak, eps), strong - eps)
    return float(weak), float(strong)


# ------------------------------------------------------------------ metrics
def ece(p, y, bins: int = 10) -> float:
    p, y = np.asarray(p), np.asarray(y, dtype=float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def _held_arrays(data, held: set, keys, thr):
    """Held-out (x, y, bonafide logit, weak, strong) concatenated over conditions `keys`."""
    parts = []
    for k in keys:
        m = np.array([u in held for u in data[k]["ids"]])
        n = int(m.sum())
        parts.append((data[k]["x"][m], data[k]["label"][m], data[k]["bf"][m],
                      np.full(n, thr[k][0]), np.full(n, thr[k][1])))
    return [np.concatenate(cols) for cols in zip(*parts)]


def evaluate(data, held: set, a: float, b: float, thr: Dict[str, Tuple[float, float]]) -> List[dict]:
    """Held-out rows per condition + POOLED; thr = {condition: (weak, strong)}."""
    rows = []
    for c in list(data) + ["POOLED"]:
        x, y, bf, weak, strong = _held_arrays(data, held, list(data) if c == "POOLED" else [c], thr)
        p = sigmoid(a * x + b)
        gen, spf = y == 0, y == 1
        eer = compute_eer(bf[gen], bf[spf])[0]
        rows.append({
            "condition": c, "n_genuine": int(gen.sum()), "n_spoof": int(spf.sum()),
            "eer_pct": 100 * eer,
            "gen_stepup_pct": 100 * float((p[gen] >= strong[gen]).mean()),
            "gen_weak_pct": 100 * float((p[gen] >= weak[gen]).mean()),
            "spoof_strong_pct": 100 * float((p[spf] >= strong[spf]).mean()),
            "spoof_weak_pct": 100 * float((p[spf] >= weak[spf]).mean()),
            "brier": float(np.mean((p - y) ** 2)), "ece": ece(p, y),
        })
    return rows


def per_condition_thresholds(data, fit_ids: set, a: float, b: float, stepup_pct: float,
                             weak_pct: float) -> Dict[str, Tuple[float, float]]:
    """(weak, strong) per condition from that condition's fit-split genuine probabilities."""
    out = {}
    for c in data:
        x, y = pool(data, fit_ids, {c})
        out[c] = choose_thresholds(sigmoid(a * x[y == 0] + b), stepup_pct, weak_pct)
    return out


# ------------------------------------------------------------------ config
def build_config(base: dict, a: float, b: float, weak: float, strong: float, provenance: dict,
                 version: str) -> dict:
    cfg = json.loads(json.dumps(base))
    cfg["version"] = version
    # l1 and l4 are still placeholders, so the file-level flag stays true (loader keeps warning).
    cfg["placeholder"] = True
    cfg["_PLACEHOLDER_NOTICE"] = (
        "Only layers.l2 was fitted on data (see provenance). L1 and L4 are still PLACEHOLDERS, "
        "hence the top-level placeholder flag stays true.")
    for k in ("l1", "l4"):
        cfg["layers"][k]["placeholder"] = True
    cfg["layers"]["l2"] = {
        "placeholder": False,
        "_note": ("FITTED. Raw x = softmax spoof probability of pretrained AASIST = sigmoid(spoof_logit - "
                  "bonafide_logit), p = sigmoid(a*x+b) = P(spoof). weak/strong are POOLED thresholds from "
                  "fit-split genuine rates; see provenance (per_condition_thresholds is informational)."),
        "platt": {"a": a, "b": b}, "weak": weak, "strong": strong,
    }
    cfg["provenance"] = provenance
    return cfg


_TABLE_HEAD = [
    "| Condition | n gen | n spoof | EER % | Genuine false step-up % | Genuine >= weak % | Spoof >= strong % | Spoof >= weak % | Brier | ECE |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]


def _table(rows) -> List[str]:
    return _TABLE_HEAD + [
        f"| {r['condition']} | {r['n_genuine']} | {r['n_spoof']} | {r['eer_pct']:.2f} | {r['gen_stepup_pct']:.2f} | "
        f"{r['gen_weak_pct']:.2f} | {r['spoof_strong_pct']:.2f} | {r['spoof_weak_pct']:.2f} | {r['brier']:.4f} | {r['ece']:.4f} |"
        for r in rows]


def render_report(rows, rows_pc, a, b, weak, strong, prov, per_cond_thr, per_cond_fit) -> str:
    L = ["# L2 calibration (Platt) and thresholds: held-out results", "",
         f"Generated by `eval/fit_calibration.py`, version `{prov['version']}`. "
         "All numbers below are on the HELD-OUT split only; no fit-split number is reported as a result.", "",
         "## Fitted values", "",
         f"- Platt: a = {a:.4f}, b = {b:.4f}, p(spoof) = sigmoid(a*x + b), x = softmax spoof probability",
         f"- Score mapping: {prov['score_mapping']}",
         f"- Thresholds on calibrated probability: weak = {weak:.6f}, strong (Step up) = {strong:.6f}",
         f"- Fit method: {prov['fit_method']}",
         f"- Split: seed {prov['split_seed']}, utterances fit/held-out = {prov['n_utterances_fit']}/{prov['n_utterances_heldout']}; "
         f"rows fit/held-out = {prov['n_rows_fit']}/{prov['n_rows_heldout']}",
         f"- Targets: strong threshold set for at most {prov['stepup_target_pct']}% genuine at/above it on the fit split; "
         f"weak threshold {prov['weak_target_pct']}% (our choice, not a team decision)", "",
         "## Held-out table: pooled thresholds (operative, in config)", "",
         "False step-up = genuine calls with L2 probability >= strong. Weak = genuine >= weak. "
         "Spoof detection = spoof calls >= strong (Step up) or >= weak. ECE uses 10 equal-width bins; "
         "Brier and ECE are for P(spoof). EER uses raw scores (threshold-free).", ""]
    L += _table(rows)
    L += ["", "## Held-out table: per-condition thresholds (informational, not in config)", "",
          "Same pooled Platt; each condition gets its own weak/strong from its own fit-split genuine "
          "probabilities at the same targets. The POOLED row applies each sample's own condition thresholds. "
          "Needs the channel condition to be known at call time, which the service does not assume.", ""]
    L += _table(rows_pc)
    L += ["", "| Condition | weak | strong |", "|---|---:|---:|"]
    L += [f"| {c} | {w:.6f} | {st:.6f} |" for c, (w, st) in per_cond_thr.items()]
    L += ["", "## Hold", "",
          "L2 alone never yields Hold under the policy table (service policy): one strong signal gives Step up, "
          "Hold needs two strong signals (L2 plus L1 or L4), a failed digit challenge, or other rules. There is "
          "therefore no separate L2 'Hold threshold' and no L2-only false-hold rate; the genuine/spoof rates at "
          "`strong` and `weak` above are what L2 contributes to those combinations. L1 and L4 are not fitted.", "",
          "## Caveats", "",
          "- x is the service's exact raw input (softmax spoof probability from both logits). It is a saturating "
          "transform of the logit margin, so Platt on x is a coarser fit than Platt on the margin would be; "
          "the cost is visible in ECE/Brier in the hardest conditions.",
          "- Channels are SIMULATED (codec/loss/noise degradation of ASVspoof 2019 LA studio audio), not real bank calls.",
          "- One dataset (ASVspoof 2019 LA eval) and a 5,000-utterance balanced subset (2,500 bona fide / 2,500 spoof) per "
          "condition, so the prior is 50% spoof; real calls are overwhelmingly genuine. Probabilities are not "
          "prevalence-adjusted, and thresholds chosen on genuine rates are what matter operationally.",
          "- Calibration and thresholds are pooled across all 11 conditions, so the single operating point is a "
          "compromise: conditions worse than average (see rows) exceed the 5% genuine step-up target, and easy ones sit under it.",
          "- The 5% target is per accent group in the team spec; ASVspoof has no accent labels, so it is applied to pooled genuine speech here. "
          "No fairness (accent gap) evidence is produced.",
          "- The split is by utterance; fit and held-out halves share speakers and attack types, so "
          "held-out numbers are optimistic relative to unseen speakers/attacks.",
          "", "## Per-condition fit (diagnostic, fit split, not results)", "",
          "| Condition | a | b |", "|---|---:|---:|"]
    for c, (aa, bb) in per_cond_fit.items():
        L.append(f"| {c} | {aa:.3f} | {bb:.3f} |")
    L.append("")
    return "\n".join(L)


def run(results: Path, out: Path, report: Optional[Path], base_path: Path, seed: int = 0,
        stepup_pct: float = STEPUP_TARGET_DEFAULT, weak_pct: float = WEAK_TARGET_DEFAULT,
        conditions: Optional[List[str]] = None, version: Optional[str] = None) -> dict:
    data = load_results(results, conditions)
    fit_ids, held_ids = split_ids(data, seed)
    assert not (fit_ids & held_ids)
    x, y = pool(data, fit_ids)
    a, b = fit_platt_np(x, y)
    pg = sigmoid(a * x[y == 0] + b)
    weak, strong = choose_thresholds(pg, stepup_pct, weak_pct)
    rows = evaluate(data, held_ids, a, b, {c: (weak, strong) for c in data})
    pc_thr = per_condition_thresholds(data, fit_ids, a, b, stepup_pct, weak_pct)
    rows_pc = evaluate(data, held_ids, a, b, pc_thr)
    per_cond = {c: fit_platt_np(*pool(data, fit_ids, {c})) for c in data}
    version = version or f"fitted-aasist-{datetime.date.today().isoformat()}"
    pooled = rows[-1]
    prov = {
        "version": version,
        "source_csvs": [d["file"] for d in data.values()],
        "split_seed": seed,
        "n_utterances_fit": len(fit_ids), "n_utterances_heldout": len(held_ids),
        "n_rows_fit": int(len(y)), "n_rows_heldout": int(pooled["n_genuine"] + pooled["n_spoof"]),
        "fit_method": "pooled over all conditions on the fit split; Newton logistic regression of spoof label on x "
                      "(see score_mapping); pooled thresholds from fit-split genuine quantiles",
        "score_mapping": SCORE_MAPPING,
        "stepup_target_pct": stepup_pct, "weak_target_pct": weak_pct,
        "heldout_pooled": {k: v for k, v in pooled.items() if k != "condition"},
        "per_condition_thresholds": {
            "note": "informational only; the operative thresholds are the pooled layers.l2 weak/strong",
            "thresholds": {c: {"weak": w, "strong": st} for c, (w, st) in pc_thr.items()},
            "heldout_pooled": {k: v for k, v in rows_pc[-1].items() if k != "condition"},
        },
    }
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    cfg = build_config(base, a, b, weak, strong, prov, version)
    Path(out).write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if report:
        Path(report).write_text(render_report(rows, rows_pc, a, b, weak, strong, prov, pc_thr, per_cond), encoding="utf-8")
    return {"a": a, "b": b, "weak": weak, "strong": strong, "rows": rows, "rows_per_cond": rows_pc, "config": cfg}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", type=Path, default=ROOT / "results",
                    help="dir of per-condition CSVs with a spoof_logit column")
    ap.add_argument("--out", type=Path, default=ROOT / "service" / "config.calibrated.json")
    ap.add_argument("--report", type=Path, default=ROOT / "results" / "CALIBRATION.md")
    ap.add_argument("--base", type=Path, default=ROOT / "service" / "config.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--stepup-target-pct", type=float, default=None,
                    help="default: genuine_stepup_target_pct from eval/targets.json")
    ap.add_argument("--weak-target-pct", type=float, default=WEAK_TARGET_DEFAULT)
    a = ap.parse_args(argv)
    t = a.stepup_target_pct
    if t is None:
        try:
            t = float(json.loads((ROOT / "eval" / "targets.json").read_text())["genuine_stepup_target_pct"]["value"])
        except Exception:
            t = STEPUP_TARGET_DEFAULT
    r = run(a.results, a.out, a.report, a.base, a.seed, t, a.weak_target_pct)
    print(f"a={r['a']:.4f} b={r['b']:.4f} weak={r['weak']:.6f} strong={r['strong']:.6f}")
    for row in r["rows"]:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
