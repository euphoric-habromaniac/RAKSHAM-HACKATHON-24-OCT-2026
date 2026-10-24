# Models

Weights are git-ignored (except the 167 KB detector `.npz` files). Verify a copy with `sha256sum`.

| File (under `ml/`) | Size (bytes) | SHA-256 |
|---|---|---|
| `live_detector/model_0p5s.npz` | 166,728 | `d1504929f630b3b17c7beef76ee6c4262e85caa357b7afbff48c2a755070785a` |
| `live_detector/model_1p0s.npz` | 166,728 | `2d7597af11803b5ecaba66fd6f66574fa9577a6ffb0108d82e608b9d7acdb13b` |
| `models/weights/aasist_baseline.pth` | 1,281,532 | `51d2d9cf0738172f61e2a384ec50a54a55363240f67c971ed55a92435bc1a1c0` |
| `models/weights/aasist_ts.pt` | 1,511,500 | `66f5d763674cdc5ef4e41a333197d32225db07a17e878a6cd87743d51d79254d` |
| `models/weights/hubert_base.pt` | 189,507,909 | `f54b40fd2802423a5643779c4861af1e9ee9c1564dc9d32f54f20b5ffba7db96` |
| `models/weights/rvc_f0D40k.pth` | 142,875,703 | `6b6ab091e70801b28e3f41f335f2fc5f3f35c75b39ae2628d419644ec2b0fa09` |
| `models/weights/rvc_f0G40k.pth` | 73,106,273 | `3b2c44035e782c4b14ddc0bede9e2f4a724d025cd073f736d4f43708453adfcb` |

## Where each model comes from

| Model | Role | Origin |
|---|---|---|
| `live_detector/model_0p5s.npz`, `model_1p0s.npz` | Live real-vs-fake detector (0.5 s and 1.0 s windows), numpy-only | Trained here by `ml/live_detector/train.py` on the Hinglish rows of `data/sehaj_dataset` |
| `models/weights/aasist_baseline.pth`, `aasist_ts.pt` | Pretrained AASIST baseline and its TorchScript export | Released AASIST weights, exported by `product/tools/export_aasist_torchscript.py` |
| `models/weights/hubert_base.pt`, `rvc_f0D40k.pth`, `rvc_f0G40k.pth` | Voice-conversion attack demo (RVC) | Public RVC and HuBERT checkpoints used for the red-team demo |
| XTTS-v2 (not copied) | Voice cloning for the fake class | Coqui XTTS-v2, downloaded from Hugging Face on first use. **Licence: CPML, non-commercial.** |

## Not copied (too large, regenerable)

- Fine-tuned XTTS checkpoints per speaker, about 19.8 GB: `derived_db/finetune/<speaker>/run/ft_model.pth`. The clones they made are already in `data/generated/`.
- ASVspoof 2019 LA raw audio (7.6 GB) and its telephone-degraded copies (5 GB): `asli-awaaz/data/raw`, `asli-awaaz/data/deg`.
- `python rak.py link-heavy` junctions these into this repo without copying.
