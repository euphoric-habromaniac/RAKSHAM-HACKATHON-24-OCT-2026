"""Speaker-embedding similarity (ECAPA) of generated clones vs the real speaker.

    python score_similarity.py "PRANJAL KUMAR" [generated_dir]
Prints cosine similarity of each clone to the mean embedding of that speaker's real clips,
plus the real-vs-real baseline (each real clip vs mean of the others).
"""
import sys
from pathlib import Path

import numpy as np
import torch
import torchaudio
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raksham_paths import RECORDINGS, GENERATED, MODELS
spk = sys.argv[1]
gen_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else GENERATED

enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir=str(MODELS / ".cache_ecapa"), local_strategy=LocalStrategy.COPY,
                                     run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"})


def emb(path):
    w, sr = torchaudio.load(str(path))
    if sr != 16000:
        w = torchaudio.functional.resample(w, sr, 16000)
    with torch.no_grad():
        e = enc.encode_batch(w.mean(0, keepdim=True)).squeeze().cpu().numpy()
    return e / np.linalg.norm(e)


real = {int(p.stem): emb(p) for p in (RECORDINGS / spk).glob("*.wav")}
fakes = {int(p.stem): emb(p) for p in (gen_dir / spk).glob("*.wav")}

mean_all = np.mean(list(real.values()), axis=0)
base = [float(e @ (np.sum([v for k2, v in real.items() if k2 != k], axis=0) / (len(real) - 1))
              / np.linalg.norm(np.mean([v for k2, v in real.items() if k2 != k], axis=0))) for k, e in real.items()]
print(f"{spk}: real-vs-other-real mean {np.mean(base):.3f} (min {min(base):.3f})")
sims = {k: float(e @ mean_all / np.linalg.norm(mean_all)) for k, e in sorted(fakes.items())}
for k, s in sims.items():
    print(f"  clone {k:>3}.wav  sim {s:.3f}")
print(f"  clone mean {np.mean(list(sims.values())):.3f}")
