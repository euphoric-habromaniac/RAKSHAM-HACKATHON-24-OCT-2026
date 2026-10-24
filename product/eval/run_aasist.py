"""Score ASVspoof 2019 LA eval audio with a pretrained AASIST model and report EER.

Model loading follows clovaai/aasist main.py: read the JSON config, take
config["model_config"], import models.<architecture>.Model, build it, then
load_state_dict(torch.load(model_path)). Scores are the bona fide logit
(batch_out[:, 1]), as in the repo's produce_evaluation_file().

Usage (from the repo root):
    python -m eval.run_aasist --aasist-repo /content/aasist --model AASIST \
        --protocol LA/ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.eval.trl.txt \
        --audio-dir LA/ASVspoof2019_LA_eval/flac --limit 5000 --device cuda \
        --out results/clean16k.csv

For a degraded condition pass the directory written by degrade.telephony as
--audio-dir. Use the same --limit and --seed for every condition so all
conditions score the same utterances.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from importlib import import_module
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402

NB_SAMP = 64600  # samples AASIST uses per utterance (about 4.04 s at 16 kHz)
AUDIO_EXTS = (".flac", ".wav")


# ---------------------------------------------------------------- helpers
def read_protocol(path: Path) -> list:
    """Parse an ASVspoof 2019 LA CM protocol into [(utt_id, label)], label 1 = bonafide.

    Lines look like: `LA_0079 LA_E_2834763 - A11 spoof`.
    """
    items = []
    with open(path, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[-1].lower()
            if key not in ("bonafide", "spoof"):
                raise ValueError(f"unexpected key '{parts[-1]}' in line: {line.strip()}")
            items.append((parts[1], 1 if key == "bonafide" else 0))
    if not items:
        raise ValueError(f"no trials found in {path}")
    return items


def subset(items: list, limit: Optional[int], seed: int = 0, balanced: bool = False) -> list:
    """Random stratified subset of at most `limit` trials.

    Default keeps the bona fide / spoof proportions of the full protocol.
    balanced=True takes limit/2 from each class (capped by availability), which
    gives a less noisy bona fide side when the protocol is spoof-heavy (the
    LA eval set is about 10 % bona fide). Same seed + same protocol = same subset.
    """
    if limit is None or limit >= len(items):
        return list(items)
    rng = random.Random(seed)
    bona = [it for it in items if it[1] == 1]
    spoof = [it for it in items if it[1] == 0]
    if balanced:
        n_b = min(len(bona), limit // 2)
        n_s = min(len(spoof), limit - n_b)
        n_b = min(len(bona), limit - n_s)
    else:
        n_b = max(1, round(limit * len(bona) / len(items))) if bona else 0
        n_s = limit - n_b
        n_s = min(n_s, len(spoof))
    out = rng.sample(bona, n_b) + rng.sample(spoof, n_s)
    out.sort(key=lambda t: t[0])
    return out


def pad_or_tile(x: np.ndarray, max_len: int = NB_SAMP) -> np.ndarray:
    """Trim to max_len, or repeat the signal until it is max_len long (AASIST's pad())."""
    n = len(x)
    if n >= max_len:
        return x[:max_len]
    reps = int(max_len / n) + 1
    return np.tile(x, reps)[:max_len]


def find_audio(audio_dir: Path, utt_id: str) -> Optional[Path]:
    for ext in AUDIO_EXTS:
        p = audio_dir / f"{utt_id}{ext}"
        if p.exists():
            return p
    return None


def write_scores(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        # rows are (utt, label, score) or (utt, label, score, spoof_logit); the
        # spoof_logit column is appended last so older readers are unaffected.
        with_spoof = bool(rows) and len(rows[0]) > 3
        w.writerow(["utt_id", "label", "score"] + (["spoof_logit"] if with_spoof else []))
        for row in rows:
            utt, lab, sc = row[:3]
            out = [utt, "bonafide" if lab == 1 else "spoof", f"{sc:.6f}"]
            if with_spoof:
                out.append(f"{row[3]:.6f}")
            w.writerow(out)


def eer_from_rows(rows: list) -> tuple:
    bona = [r[2] for r in rows if r[1] == 1]
    spoof = [r[2] for r in rows if r[1] == 0]
    return compute_eer(bona, spoof) + (len(bona), len(spoof))


# ------------------------------------------------------------------ model
def load_model(aasist_repo: Path, model_name: str, device, weights: Optional[Path] = None):
    """Build AASIST / AASIST-L the way the repo's main.py does."""
    import torch

    repo = aasist_repo.resolve()
    cfg_path = repo / "config" / f"{model_name}.conf"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path} (is --aasist-repo a clone of clovaai/aasist?)")
    with open(cfg_path, "r") as f:
        config = json.loads(f.read())
    model_config = config["model_config"]

    sys.path.insert(0, str(repo))
    module = import_module("models.{}".format(model_config["architecture"]))
    model = getattr(module, "Model")(model_config).to(device)

    wpath = Path(weights) if weights else Path(config["model_path"])
    if not wpath.is_absolute():
        wpath = repo / wpath
    if not wpath.exists():
        raise FileNotFoundError(f"weights not found: {wpath}")
    model.load_state_dict(torch.load(wpath, map_location=device))
    model.eval()
    return model


def score_files(model, paths: list, device, batch_size: int = 32, num_workers: int = 2,
                return_spoof: bool = False):
    """Return the bona fide logit for each path (same order).

    With return_spoof=True return (bonafide_logits, spoof_logits) instead.
    """
    import soundfile as sf
    import torch
    from torch.utils.data import DataLoader, Dataset

    class _DS(Dataset):
        def __len__(self):
            return len(paths)

        def __getitem__(self, i):
            x, sr = sf.read(str(paths[i]), dtype="float32", always_2d=True)
            x = x.mean(axis=1)
            if sr != 16000:
                raise ValueError(f"{paths[i]} is {sr} Hz, AASIST needs 16 kHz")
            return torch.from_numpy(pad_or_tile(x).copy())

    try:
        from tqdm import tqdm
    except Exception:
        tqdm = lambda it, **k: it  # noqa: E731
    scores, spoof_scores = [], []
    loader = DataLoader(_DS(), batch_size=batch_size, shuffle=False, num_workers=num_workers)
    with torch.no_grad():
        for batch in tqdm(loader, desc="scoring"):
            _, out = model(batch.to(device))
            scores.extend(out[:, 1].cpu().numpy().ravel().tolist())
            spoof_scores.extend(out[:, 0].cpu().numpy().ravel().tolist())
    if return_spoof:
        return scores, spoof_scores
    return scores


# -------------------------------------------------------------------- CLI
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aasist-repo", type=Path, required=True)
    ap.add_argument("--model", choices=["AASIST", "AASIST-L"], default="AASIST")
    ap.add_argument("--protocol", type=Path, required=True)
    ap.add_argument("--audio-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None, help="random stratified subset size")
    ap.add_argument("--balanced", action="store_true", help="with --limit: half bona fide, half spoof")
    ap.add_argument("--seed", type=int, default=0, help="subset seed (keep fixed across conditions)")
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--weights", type=Path, default=None, help="override the config's model_path")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--num-workers", type=int, default=0 if os.name == "nt" else 2,
                    help="DataLoader workers (default 0 on Windows: the local Dataset is not picklable under spawn)")
    ap.add_argument("--skip-missing", action="store_true", help="skip trials whose audio file is absent")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    import torch

    if a.device == "cuda" and not torch.cuda.is_available():
        print("error: --device cuda requested but CUDA is not available; use --device cpu", file=sys.stderr)
        return 2
    device = torch.device(a.device)

    items = subset(read_protocol(a.protocol), a.limit, a.seed, a.balanced)
    found, missing = [], 0
    for utt, lab in items:
        p = find_audio(a.audio_dir, utt)
        if p is None:
            missing += 1
        else:
            found.append((utt, lab, p))
    if missing and not a.skip_missing:
        print(f"error: {missing} of {len(items)} audio files missing in {a.audio_dir} "
              "(use --skip-missing to ignore, but then conditions may cover different utterances)",
              file=sys.stderr)
        return 2
    if not found:
        print("error: no audio files found", file=sys.stderr)
        return 2

    model = load_model(a.aasist_repo, a.model, device, a.weights)
    scores, spoof_scores = score_files(model, [p for _, _, p in found], device, a.batch_size,
                                       a.num_workers, return_spoof=True)
    rows = [(u, l, s, sp) for (u, l, _), s, sp in zip(found, scores, spoof_scores)]
    write_scores(a.out, rows)
    eer, thr, nb, ns = eer_from_rows(rows)
    print(f"{a.model} on {a.audio_dir}: n_bonafide={nb} n_spoof={ns} EER={eer * 100:.2f}% (threshold {thr:.4f})")
    print(f"scores written to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
