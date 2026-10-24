# RAKSHAM

Everything from the hackathon in one folder: the Asli Awaaz bank-call security layer, the Hinglish real/fake voice data, the live detector, the demo, the decks and the design system.

```
RAKSHAM/
├── rak.py           one entry point (see below)
├── product/         Asli Awaaz decision service, screens, simulator, evaluation, tests   (decision layer)
├── ml/
│   ├── live_detector/   numpy-only detector, demo page, case-storage server
│   ├── voice_data/      recording kit scripts, clone generation, fine-tuning, dataset builder
│   ├── notebooks/       Sehaj's notebook (original and executed copy)
│   └── models/          weights (git-ignored) and MODELS.md with SHA-256
├── data/
│   ├── recordings_awaaz/   300 real clips, consent files, manifests
│   ├── generated/          300 voice clones and their manifest
│   └── sehaj_dataset/      labels.csv + audio: 15,000 English + 1,800 Hinglish rows
├── cases/           calls saved by the demo (audio + analysis), local only
├── deck/            finale deck (finale/) and the Round 1 material (round1/)
├── design-system/   tokens, logos, icons, components
├── results/         logs and scores that back the numbers we quote
```

## Run it

```
python rak.py setup --ml    # once: .venv + dependencies (+ CPU torch so every test runs)
python rak.py check         # doctor + data-check + 427 tests + end-to-end smoke
python rak.py demo          # Voice Check demo + case storage:  http://127.0.0.1:8765/
python rak.py service --live   # Asli Awaaz service on :8000 with our detector as L2
python rak.py precommit     # before every commit
```

## Move it to another computer

```
python rak.py pack          # writes ../RAKSHAM_portable_<date>.zip (about 2.4 GB: code, data, models, git history; no .venv)
# on the other computer: unzip, then
python rak.py setup --ml    # needs Python 3.10+ and internet, builds a fresh .venv (a copied .venv never works)
python rak.py check         # everything passes, as it did in a relocated test copy with spaces in its path
python rak.py demo          # works even before setup: the demo server needs only Python itself
```

- `pack` refuses to run while junction links from `link-heavy` exist, because a zip tool would follow them into the 32 GB of original data. If you zip by hand, remove those links first (`rmdir`, never a recursive delete).
- The zip contains the real recordings, clones and saved calls (biometric data, 90-day consent). Share it only with the people who signed.
- `ml/notebooks/DC and MT (original).ipynb` keeps Sehaj's original Mac paths on purpose; the `_executed` copy uses relative paths (run it from `ml/notebooks`).

## How the pieces fit

- The product's L2 (synthetic-speech check) can use our detector: `ASLI_L2_BACKEND=live` (adapter: `product/service/live_scorer.py`). No speech in the audio means the scorer raises and the engine falls back to Step up.
- The demo page runs the same detector in JavaScript (verified identical to Python) and saves finished calls to `cases/`.
- `data/sehaj_dataset/labels.csv` is the single source of truth for training and testing. Split rules and limits are in its README.

## Read before quoting any number

- It was tested on **3 speakers and 1 cloner (XTTS-v2)**; the Hinglish validation split shares speakers with training; only the test split (one speaker) is speaker-disjoint.
- Real strangers are mostly called fake: it confirms enrolled voices, it is not a general fake-voice detector.

## Data and privacy

Recordings are biometric data signed for 90-day retention. Audio, consent files and saved calls are git-ignored; keep them on this machine. The big regenerable data (ASVspoof audio 12.6 GB, fine-tune checkpoints 19.8 GB) stays in the original folders: `python rak.py link-heavy` junctions it in without copying. Remove a junction with `rmdir <link>`, never with a recursive delete.
