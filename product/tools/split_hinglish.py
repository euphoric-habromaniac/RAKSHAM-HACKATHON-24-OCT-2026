"""Deterministic speaker-disjoint split of the Hinglish set, plus the claim level it allows.

    python -m tools.split_hinglish --hinglish data/hinglish [--seed 0] [--force]

Rule (docs/HINGLISH_PLAN.md 2.1 and 2.5), N = speakers in the manifest:
    N < 4    everyone held out; no tuning on Hinglish; no result claim beyond S1 text
    4..7     everyone held out (test-only); claim up to S3 (evaluation, no Hinglish tuning)
    8..9     3-4 train, 1 val, 4 held out
    10+      rest train, 1 val, max(3, ceil(0.3 N)) held out
Speakers are shuffled with the seed inside each accent group, then dealt out
round-robin across groups (held out first), so held-out spans as many accent
groups as possible. A speaker's real and spoof clips always share a split.
Once splits.json exists it is frozen: a different speaker set needs --force.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hinglish_data import DEFAULT_DIR, read_manifest, speaker_accents  # noqa: E402


def split_sizes(n: int) -> tuple:
    """-> (n_train, n_val, n_heldout)."""
    if n < 8:
        return 0, 0, n
    held = 4 if n <= 9 else max(3, math.ceil(0.3 * n))
    return n - held - 1, 1, held


def dealing_order(accents: dict, seed: int) -> list:
    """Speakers interleaved across accent groups (largest group first), seeded shuffle inside each."""
    rng = random.Random(seed)
    groups = defaultdict(list)
    for spk in sorted(accents):
        groups[accents[spk]].append(spk)
    queues = []
    for name in sorted(groups, key=lambda g: (-len(groups[g]), g)):
        rng.shuffle(groups[name])
        queues.append(groups[name])
    order = []
    while any(queues):
        order += [q.pop(0) for q in queues if q]
    return order


def assign_splits(accents: dict, seed: int = 0) -> dict:
    n_train, n_val, n_held = split_sizes(len(accents))
    order = dealing_order(accents, seed)
    out = {s: "heldout" for s in order[:n_held]}
    out.update({s: "val" for s in order[n_held:n_held + n_val]})
    out.update({s: "train" for s in order[n_held + n_val:]})
    assert n_train == sum(v == "train" for v in out.values())
    return out


def claim_level(assign: dict, accents: dict, rows: list) -> str:
    """Highest stage of the plan's claim ladder this data can support (S0..S4)."""
    n = len(assign)
    held = [s for s, v in assign.items() if v == "heldout"]
    held_accents = {accents[s] for s in held} - {"unknown"}
    has_clones = any(r["label"] == "spoof" and assign.get(r["speaker_id"]) == "heldout" for r in rows)
    if n < 4:
        return ("S1 text only: fewer than 4 speakers. Say 'we recorded N consenting speakers'. "
                "No Hinglish result, no Hinglish tuning.")
    base = ("S2 is possible: held-out speakers have spoof clips." if has_clones else
            "S2 needs spoof clips for held-out speakers; without them only genuine false-reject can be reported.")
    if n < 8:
        return f"S3 at most (test-only, {n} speakers): evaluate, do not tune on Hinglish. {base}"
    if len(held_accents) < 2:
        return f"S3 at most: held-out speakers span fewer than 2 accent groups. {base}"
    return (f"S4 possible ({len(held)} held-out speakers in {len(held_accents)} accent groups): "
            f"tune on train speakers, compare with S3 on held-out. S5 additionally needs the calibration refit. {base}")


def build_splits(rows: list, seed: int) -> dict:
    accents = speaker_accents(rows)
    assign = assign_splits(accents, seed)
    return {"seed": seed, "n_speakers": len(assign), "speakers": dict(sorted(assign.items())),
            "accent": dict(sorted(accents.items())), "claim_level": claim_level(assign, accents, rows)}


def check_disjoint(splits: dict) -> None:
    by = defaultdict(set)
    for spk, name in splits["speakers"].items():
        by[name].add(spk)
    names = list(by)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not (by[a] & by[b]), f"speaker overlap between {a} and {b}"


def summary(splits: dict) -> str:
    lines = []
    for name in ("train", "val", "heldout"):
        spks = [s for s, v in splits["speakers"].items() if v == name]
        accs = sorted({splits["accent"][s] for s in spks})
        lines.append(f"{name:<8} {len(spks):>2} speakers  accents: {', '.join(accs) or '-'}")
    lines.append(f"CLAIM LEVEL: {splits['claim_level']}")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hinglish", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="overwrite a frozen splits.json")
    a = ap.parse_args(argv)

    rows = read_manifest(a.hinglish / "manifest.csv")
    if not rows:
        print(f"error: no manifest rows in {a.hinglish}; run tools.ingest_hinglish first", file=sys.stderr)
        return 2
    new = build_splits(rows, a.seed)
    check_disjoint(new)
    path = a.hinglish / "splits.json"
    if path.exists() and not a.force:
        old = json.loads(path.read_text(encoding="utf-8"))
        if set(old["speakers"]) != set(new["speakers"]):
            print("error: splits.json is frozen but the speaker set changed "
                  "(re-splitting could move a trained-on speaker into held-out). Use --force only "
                  "if nothing has been trained yet.", file=sys.stderr)
            return 2
        new = dict(old, claim_level=claim_level(old["speakers"], old["accent"], rows))  # assignment frozen
    path.write_text(json.dumps(new, indent=2), encoding="utf-8")
    print(summary(new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
