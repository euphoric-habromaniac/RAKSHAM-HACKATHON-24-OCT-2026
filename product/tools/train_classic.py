"""Classic-ML baseline (MFCC stats -> RandomForest / MLP) on data/sehaj_dataset.

    python -m tools.train_classic [--include-hinglish-train]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from eval.eer import compute_eer  # noqa: E402

DATA = ROOT / "data/sehaj_dataset"
OUT = ROOT / "results_classic"
_MFCC = torchaudio.transforms.MFCC(sample_rate=16000, n_mfcc=20,
                                   melkwargs={"n_fft": 512, "hop_length": 160, "n_mels": 40})


def clip_features(path: Path) -> np.ndarray:
    """20 MFCC + 20 delta, mean and std over time -> 80-dim vector."""
    x, _ = sf.read(str(path), dtype="float32")
    m = _MFCC(torch.from_numpy(x))
    f = torch.cat([m, torchaudio.functional.compute_deltas(m)], dim=0)
    return torch.cat([f.mean(1), f.std(1)]).numpy()


def load_features(files, name: str = "mfcc80") -> np.ndarray:
    """Per-file cache in features_<name>.npy (dict file -> vector); only missing files are computed."""
    cache_path = DATA / f"features_{name}.npy"
    cache = np.load(cache_path, allow_pickle=True).item() if cache_path.exists() else {}
    todo = [f for f in files if f not in cache]
    for i, f in enumerate(todo, 1):
        cache[f] = clip_features(DATA / f)
        if i % 2000 == 0:
            print(f"features {i}/{len(todo)}", flush=True)
    if todo:
        np.save(cache_path, cache, allow_pickle=True)
    return np.stack([cache[f] for f in files])


def train_mask(df: pd.DataFrame, include_hinglish: bool) -> pd.Series:
    m = df.split == "train"
    return m if include_hinglish else m & (df.language != "hinglish")


def eval_rows(df, X, scores, model: str) -> list:
    rows = []
    for (lang, cond, split), g in df[df.split.isin(["val", "test"])].groupby(["language", "condition", "split"]):
        y, s = g.label_id.to_numpy(), scores[g.index]
        if len(set(y)) < 2:
            continue
        eer, thr = compute_eer(s[y == 1], s[y == 0])
        rows.append({"model": model, "language": lang, "condition": cond, "split": split,
                     "eer": 100 * eer, "acc": 100 * float(((s >= 0.5) == (y == 1)).mean()), "n": len(g)})
    return rows


def write_compare(res: pd.DataFrame) -> None:
    OUT.mkdir(exist_ok=True)
    lines = ["# Classic-ML baseline (MFCC mean+std, 20 MFCC + delta)", "",
             "| model | language | condition | split | EER % | acc % | n |", "|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        lines.append(f"| {r.model} | {r.language} | {r.condition} | {r.split} | {r.eer:.2f} | {r.acc:.1f} | {r.n} |")
    lines += ["", "Notes:",
              "- Trained on split=train, language=english only (Hinglish is never trained on unless "
              "`--include-hinglish-train`); Hinglish rows are reported separately by language.",
              "- Reference: AASIST pretrained, on the same kind of subset, scored clean 0.92% EER and "
              "gsm 7.36% EER (results/SUMMARY.md).",
              "- Not the same subset split or training, so treat as a rough yardstick, not a head-to-head."]
    (OUT / "COMPARE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    ap = argparse.ArgumentParser()
    ap.add_argument("--include-hinglish-train", action="store_true")
    a = ap.parse_args()
    df = pd.read_csv(DATA / "labels.csv", keep_default_na=False)
    X = load_features(df.file.tolist())
    tr = train_mask(df, a.include_hinglish_train).to_numpy()
    print(f"train rows: {tr.sum()}")
    models = {
        "RandomForest": RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=0),
        "MLP": make_pipeline(StandardScaler(), MLPClassifier((128, 64), max_iter=300, early_stopping=True,
                                                             random_state=0)),
    }
    rows = []
    for name, m in models.items():
        m.fit(X[tr], df.label_id[tr])
        rows += eval_rows(df, X, m.predict_proba(X)[:, 1], name)
    res = pd.DataFrame(rows)
    write_compare(res)
    print(res.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
