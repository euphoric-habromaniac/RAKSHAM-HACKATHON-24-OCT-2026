"""Generate AI-cloned (spoof) counterparts of the consented real recordings with XTTS-v2.

For every real clip N.wav of every consented speaker, synthesise the same prompt text in that
speaker's cloned voice -> generated/<Speaker>/N.wav (16 kHz mono 16-bit, same as the real set).
Resumable: existing outputs are skipped. Writes generated/manifest_generated.csv.

    python generate_clones.py                 # all speakers, all prompts
    python generate_clones.py --limit 3       # smoke test, 3 clips per speaker
    python generate_clones.py --hinglish-lang en
"""
import argparse
import csv
import json
import re
import wave
from pathlib import Path

import numpy as np
import torch
import torchaudio

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raksham_paths import RECORDINGS as REC, GENERATED as OUT
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
LANG = {"hindi": "hi", "english": "en"}
HI_DIGITS = "शून्य एक दो तीन चार पाँच छह सात आठ नौ".split()


def tts_text(text: str, lang: str) -> str:
    """XTTS cannot expand digits for Hindi; read them out digit by digit as the speakers did."""
    if lang == "hi":
        return re.sub(r"[0-9]", lambda m: f" {HI_DIGITS[int(m.group())]} ", text).replace("  ", " ")
    return text


def consented(speaker_dir: Path) -> bool:
    c = json.loads((speaker_dir / "consent.json").read_text(encoding="utf-8"))
    return bool(c.get("signed") and c.get("allow_voice_cloning"))


def pick_refs(rows, speaker_dir: Path, n: int):
    """Clean 5-12s clips (no clipping/warnings), spread across languages, closest to median level."""
    good = [r for r in rows
            if r["clipped"].lower() != "true" and not r["warnings"] and 5 <= float(r["duration_s"]) <= 12]
    if not good:
        good = rows
    med = np.median([float(r["rms_dbfs"]) for r in good])
    good.sort(key=lambda r: abs(float(r["rms_dbfs"]) - med))
    picked, seen = [], {}
    for r in good:
        if seen.get(r["language"], 0) < max(1, n // 3 + 1) and len(picked) < n:
            seen[r["language"]] = seen.get(r["language"], 0) + 1
            picked.append(r)
    return [speaker_dir / f"{r['sentence_number']}.wav" for r in picked]


def save16k(wav: np.ndarray, sr: int, path: Path):
    t = torchaudio.functional.resample(torch.tensor(wav, dtype=torch.float32).unsqueeze(0), sr, 16000)
    pcm = (t.squeeze(0).clamp(-1, 1).numpy() * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm.tobytes())
    return len(pcm) / 16000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="clips per speaker (0 = all)")
    ap.add_argument("--n-refs", type=int, default=4)
    ap.add_argument("--hinglish-lang", default="hi", choices=["hi", "en"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    from TTS.api import TTS
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tts = TTS(MODEL).to(dev)

    with open(REC / "manifest_master.csv", encoding="utf-8-sig", newline="") as f:
        all_rows = list(csv.DictReader(f))

    man_path = OUT / "manifest_generated.csv"
    OUT.mkdir(exist_ok=True)
    done_rows = []
    if man_path.exists():
        with open(man_path, encoding="utf-8", newline="") as f:
            done_rows = list(csv.DictReader(f))
    done = {r["file"] for r in done_rows}

    for sdir in sorted(p for p in REC.iterdir() if p.is_dir()):
        if not consented(sdir):
            print(f"skip {sdir.name}: no cloning consent"); continue
        rows = sorted((r for r in all_rows if r["full_name"] == sdir.name), key=lambda r: int(r["sentence_number"]))
        refs = pick_refs(rows, sdir, a.n_refs)
        ref_ids = {r.name for r in refs if r.parent == sdir}
        print(f"{sdir.name}: refs {[str(r.name) for r in refs]}")
        for r in rows[: a.limit or None]:
            rel = f"{sdir.name}/{r['sentence_number']}.wav"
            if rel in done:
                continue
            lang = LANG.get(r["language"], a.hinglish_lang)
            real_dur = float(r["duration_s"])
            text = tts_text(r["prompt_text"], lang)
            best = None
            for attempt in range(4):  # retry runaway generations (> 2x the real clip) with a new seed, keep the shortest
                torch.manual_seed(a.seed + int(r["sentence_number"]) + 1000 * attempt)
                wav = np.asarray(tts.tts(text=text, speaker_wav=[str(x) for x in refs], language=lang))
                if best is None or len(wav) < len(best):
                    best = wav
                if len(wav) / tts.synthesizer.output_sample_rate <= 2 * real_dur:
                    break
            wav = best
            dur = save16k(wav, tts.synthesizer.output_sample_rate, OUT / rel)
            done_rows.append({
                "file": rel, "label": "spoof", "generator": "xtts_v2", "speaker_id": r["speaker_id"],
                "full_name": r["full_name"], "sentence_number": r["sentence_number"], "phrase_id": r["phrase_id"],
                "language": r["language"], "tts_language": lang, "prompt_text": r["prompt_text"], "tts_text": text,
                "duration_s": f"{dur:.2f}", "paired_real_file": r["file"],
                "reference_clips": ";".join(x.name for x in refs),
                "reference_overlaps_real": str(f"{r['sentence_number']}.wav" in ref_ids).lower(),
                "sample_rate": 16000, "channels": 1, "bit_depth": 16,
            })
            with open(man_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(done_rows[0])); w.writeheader(); w.writerows(done_rows)
            print(f"  {rel} [{lang}] {dur:.1f}s")


if __name__ == "__main__":
    main()
