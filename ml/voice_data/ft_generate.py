"""Generate clones of one speaker's 100 script sentences with a fine-tuned XTTS-v2 checkpoint.

    python ft_generate.py "PRANJAL KUMAR" finetune/pranjal10/run --tag xtts_v2_ft_pranjal10 --trained 61,67,100,...
Writes generated/<Speaker>/N.wav (16 kHz mono 16-bit) and replaces that speaker's rows in
generated/manifest_generated.csv. Reference clips = the same clean clips generate_clones.py picks.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from generate_clones import LANG, OUT, REC, pick_refs, save16k, tts_text
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts

ap = argparse.ArgumentParser()
ap.add_argument("speaker")
ap.add_argument("run_dir", type=Path)
ap.add_argument("--tag", default="xtts_v2_ft")
ap.add_argument("--trained", default="", help="comma list of sentence numbers used for fine-tuning")
ap.add_argument("--hinglish-lang", default="hi")
ap.add_argument("--limit", type=int, default=0)
a = ap.parse_args()

run = a.run_dir.resolve()
base = run / "XTTS_v2.0_original_model_files"
ckpt = next(iter(sorted((p for p in run.glob("GPT_XTTS_FT-*/best_model.pth")), key=lambda p: p.stat().st_mtime)[-1:]))
model_pth = run / "ft_model.pth"
if not model_pth.exists() or model_pth.stat().st_mtime < ckpt.stat().st_mtime:
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)["model"]
    sd = {k[len("xtts."):]: v for k, v in sd.items() if k.startswith("xtts.") and "dvae" not in k}
    torch.save({"model": sd}, model_pth)
    print(f"extracted {len(sd)} tensors from {ckpt.name}")

cfg = XttsConfig(); cfg.load_json(str(base / "config.json"))
model = Xtts.init_from_config(cfg)
model.load_checkpoint(cfg, checkpoint_path=str(model_pth), vocab_path=str(base / "vocab.json"), use_deepspeed=False)
model.cuda().eval()

with open(REC / "manifest_master.csv", encoding="utf-8-sig", newline="") as f:
    rows = sorted((r for r in csv.DictReader(f) if r["full_name"] == a.speaker), key=lambda r: int(r["sentence_number"]))
sdir = REC / a.speaker
refs = [str(p) for p in pick_refs(rows, sdir, 4)]
latent, spk_emb = model.get_conditioning_latents(audio_path=refs, gpt_cond_len=model.config.gpt_cond_len,
                                                 max_ref_length=model.config.max_ref_len,
                                                 sound_norm_refs=model.config.sound_norm_refs)
trained = set(a.trained.split(",")) if a.trained else set()

man_path = OUT / "manifest_generated.csv"
old = list(csv.DictReader(open(man_path, encoding="utf-8", newline=""))) if man_path.exists() else []
keep = [r for r in old if r["full_name"] != a.speaker]
new = []
for r in rows[: a.limit or None]:
    n = r["sentence_number"]
    lang = LANG.get(r["language"], a.hinglish_lang)
    text = tts_text(r["prompt_text"], lang)
    real_dur = float(r["duration_s"]); best = None
    for attempt in range(4):
        torch.manual_seed(int(n) + 1000 * attempt)
        out = model.inference(text, lang, latent, spk_emb, temperature=0.7, enable_text_splitting=False)
        wav = np.asarray(out["wav"])
        if best is None or len(wav) < len(best):
            best = wav
        if len(wav) / 24000 <= 2 * real_dur:
            break
    dur = save16k(best, 24000, OUT / a.speaker / f"{n}.wav")
    new.append({
        "file": f"{a.speaker}/{n}.wav", "label": "spoof", "generator": a.tag, "speaker_id": r["speaker_id"],
        "full_name": a.speaker, "sentence_number": n, "phrase_id": r["phrase_id"], "language": r["language"],
        "tts_language": lang, "prompt_text": r["prompt_text"], "tts_text": text, "duration_s": f"{dur:.2f}",
        "paired_real_file": r["file"], "reference_clips": ";".join(Path(x).name for x in refs),
        "reference_overlaps_real": str(Path(sdir / f'{n}.wav').as_posix() in {Path(x).as_posix() for x in refs}).lower(),
        "sample_rate": 16000, "channels": 1, "bit_depth": 16, "finetune_trained_on_sentence": str(n in trained).lower(),
    })
    print(f"  {a.speaker}/{n}.wav [{lang}] {dur:.1f}s", flush=True)
fields = list(new[0])
for r in keep:
    r.setdefault("finetune_trained_on_sentence", "false")
with open(man_path, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(keep + new)
print("DONE", len(new))
