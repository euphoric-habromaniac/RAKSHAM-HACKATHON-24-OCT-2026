"""Append our consented real recordings + XTTS-v2 clones to the sehaj_dataset as language=hinglish.

    python add_to_sehaj.py            # copies audio, builds gsm/g711u with product degrade code, appends labels.csv

Layout:  audio/hinglish/{clean,gsm,g711u}/<speaker_id>_<NNN>_<real|fake>.wav
Splits:  test = YASH CHAUHAN (speaker-disjoint); train/val = KUSHAGRA + PRANJAL KUMAR, with sentence numbers
         divisible by 5 as val (same speakers as train, different sentences -> val is NOT speaker-disjoint).
"""
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raksham_paths import SEHAJ as DS, RECORDINGS, GENERATED, PRODUCT
sys.path.insert(0, str(PRODUCT))  # for degrade.telephony
from degrade.telephony import degrade_file  # noqa: E402

CONDS = ["clean", "gsm", "g711u"]
TEST_SPEAKER = "YASH CHAUHAN"
REC, GEN = RECORDINGS, GENERATED
COLUMNS = ["file", "label", "label_id", "split", "speaker_id", "language", "fake_type", "condition", "source", "orig_label"]

labels = DS / "labels.csv"
existing = list(csv.DictReader(open(labels, encoding="utf-8", newline="")))
if any(r["language"] == "hinglish" for r in existing):
    sys.exit("hinglish rows already in labels.csv - refusing to append twice")
shutil.copy(labels, DS / "labels.before_hinglish.csv")

gen = {(r["full_name"], int(r["sentence_number"])): r
       for r in csv.DictReader(open(GEN / "manifest_generated.csv", encoding="utf-8", newline=""))}
real_rows = [r for r in csv.DictReader(open(REC / "manifest_master.csv", encoding="utf-8-sig", newline=""))]

new = []
for r in real_rows:
    name, n, spk = r["full_name"], int(r["sentence_number"]), r["speaker_id"]
    split = "test" if name == TEST_SPEAKER else ("val" if n % 5 == 0 else "train")
    g = gen[(name, n)]
    for kind, src in (("real", REC / name / f"{n}.wav"), ("fake", GEN / name / f"{n}.wav")):
        stem = f"{spk}_{n:03d}_{kind}"
        for cond in CONDS:
            dst = DS / "audio" / "hinglish" / cond / f"{stem}.wav"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if cond == "clean":
                shutil.copy(src, dst)
            else:
                degrade_file(src, dst, cond, seed_key=stem)
            real = kind == "real"
            new.append({"file": f"audio/hinglish/{cond}/{stem}.wav", "label": kind, "label_id": int(real),
                        "split": split, "speaker_id": spk, "language": "hinglish",
                        "fake_type": "" if real else g["generator"], "condition": cond,
                        "source": "asli_awaaz", "orig_label": "bonafide" if real else "spoof"})
    if n == 100:
        print("done", name, flush=True)

with open(labels, "a", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
    w.writerows(new)
print("appended", len(new), "rows")
