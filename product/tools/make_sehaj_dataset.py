"""Build data/sehaj_dataset (English Stage A) from the ASVspoof2019 LA eval subset.

    python -m tools.make_sehaj_dataset            # build
    python -m tools.make_sehaj_dataset --check    # validate
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
FLAC = ROOT / "data/raw/LA/subset5000/flac"
PROTO = ROOT / "data/raw/LA/ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.eval.trl.txt"
DEG = ROOT / "data/deg"
OUT = ROOT / "data/sehaj_dataset"
SR = 16000
CONDITIONS = ["clean", "gsm", "g711u"]
COLUMNS = ["file", "label", "label_id", "split", "speaker_id", "language", "fake_type",
           "condition", "source", "orig_label"]


def parse_protocol(path: Path, wanted: set) -> dict:
    """utt -> (speaker, attack, orig_label) for utts in `wanted`."""
    out = {}
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) >= 5 and p[1] in wanted:
            out[p[1]] = (p[0], p[3], p[4])
    return out


def assign_splits(speakers, seed: int = 0, frac=(0.70, 0.15)) -> dict:
    """Seeded speaker-disjoint split, ~70/15/15 by speaker count."""
    spk = sorted(set(speakers))
    random.Random(seed).shuffle(spk)
    n_tr, n_va = round(len(spk) * frac[0]), round(len(spk) * frac[1])
    names = ["train"] * n_tr + ["val"] * n_va
    names += ["test"] * (len(spk) - len(names))
    return dict(zip(spk, names))


def to_wav16(src: Path, dst: Path) -> None:
    """Write src as 16 kHz mono PCM16 wav (resample/downmix only if needed)."""
    x, sr = sf.read(str(src), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), np.clip(x, -1, 1), SR, subtype="PCM_16")


def build_rows(utts: dict, splits: dict) -> list:
    rows = []
    for utt, (spk, attack, orig) in sorted(utts.items()):
        real = orig == "bonafide"
        for cond in CONDITIONS:
            rows.append({
                "file": f"audio/{cond}/{utt}.wav", "label": "real" if real else "fake",
                "label_id": int(real), "split": splits[spk], "speaker_id": spk,
                "language": "english", "fake_type": "" if real else attack,
                "condition": cond, "source": "asvspoof2019", "orig_label": orig})
    return rows


def build() -> None:
    utts = parse_protocol(PROTO, {p.stem for p in FLAC.glob("*.flac")})
    splits = assign_splits([v[0] for v in utts.values()])
    for i, utt in enumerate(sorted(utts), 1):
        to_wav16(FLAC / f"{utt}.flac", OUT / "audio/clean" / f"{utt}.wav")
        for cond in CONDITIONS[1:]:
            to_wav16(DEG / cond / f"{utt}.wav", OUT / "audio" / cond / f"{utt}.wav")
        if i % 500 == 0:
            print(f"{i}/{len(utts)}", flush=True)
    df = pd.DataFrame(build_rows(utts, splits), columns=COLUMNS)
    df.to_csv(OUT / "labels.csv", index=False)
    (OUT / "README.md").write_text(readme(df), encoding="utf-8")
    print(f"wrote {len(df)} rows")


def readme(df: pd.DataFrame) -> str:
    def table(by):
        t = df.groupby(by).size().unstack(fill_value=0)
        head = f"| {t.index.name} | " + " | ".join(map(str, t.columns)) + " |"
        rows = [f"| {i} | " + " | ".join(map(str, r)) + " |" for i, r in zip(t.index, t.values)]
        return chr(10).join([head, "|---" * (len(t.columns) + 1) + "|"] + rows)
    return f"""# Sehaj dataset - Stage A (English)

Real vs fake (spoof) speech clips for training a deepfake-voice detector.
All audio is **16 kHz, mono, 16-bit WAV**. Total rows: {len(df)}.

## labels.csv columns
| column | meaning |
|---|---|
| file | path relative to this folder, e.g. `audio/gsm/LA_E_1002903.wav` |
| label | `real` or `fake` |
| label_id | 1 = real, 0 = fake |
| split | `train`, `val` or `test` |
| speaker_id | ASVspoof speaker (e.g. LA_0079) |
| language | `english` now; Hinglish rows will be appended with `hinglish` |
| fake_type | attack code A07..A19 for fakes, empty for real |
| condition | `clean`, `gsm` (GSM phone codec) or `g711u` (landline mu-law) |
| source | `asvspoof2019` |
| orig_label | original ASVspoof label, `bonafide` or `spoof` |

## Splits
Splits are **speaker-disjoint** (seeded, about 70/15/15 by speakers): a speaker, and every
variant (clean/gsm/g711u) of an utterance, lives in exactly one split. Never mix them,
warna test scores jhoothe ho jayenge.

## Counts (rows)
Per split and label:

{table(["split", "label"])}

Per split and condition:

{table(["split", "condition"])}

Per condition and label:

{table(["condition", "label"])}

## Loading
```python
import pandas as pd, soundfile as sf
df = pd.read_csv("labels.csv")
train = df[(df.split == "train") & (df.language == "english")]
x, sr = sf.read(train.file.iloc[0])   # sr == 16000
y = train.label_id                    # 1 = real, 0 = fake
```

## Honest limits
- English only. No Hinglish yet (rows will be appended with `language=hinglish`).
- Fakes are the ASVspoof 2019 LA attacks (A07..A19) only; a new TTS/voice-cloning system may behave differently.
- gsm and g711u are *simulated* phone channels (codec applied in software), not real calls.
- Scores on this data do not promise the same accuracy on real calls.
"""


def check() -> int:
    df = pd.read_csv(OUT / "labels.csv", keep_default_na=False)
    bad = []
    if list(df.columns) != COLUMNS:
        bad.append(f"columns: {list(df.columns)}")
    for f in df.file:
        p = OUT / f
        if not p.exists():
            bad.append(f"missing {f}")
            continue
        i = sf.info(str(p))
        if (i.samplerate, i.channels, i.subtype) != (SR, 1, "PCM_16"):
            bad.append(f"format {f}: {i.samplerate} {i.channels} {i.subtype}")
    leak = df.groupby("speaker_id").split.nunique()
    bad += [f"speaker in 2 splits: {s}" for s in leak[leak > 1].index]
    if df.duplicated().any() or df.file.duplicated().any():
        bad.append("duplicate rows")
    print(df.groupby(["split", "label"]).size().unstack(fill_value=0))
    print(df.groupby(["split", "condition"]).size().unstack(fill_value=0))
    print("speakers per split:", df.groupby("split").speaker_id.nunique().to_dict())
    print("PROBLEMS:" if bad else "OK", *bad[:20], sep="\n")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        sys.exit(check())
    build()
