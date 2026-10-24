"""One place for every path in the RAKSHAM repo, derived from this file's location (no absolute paths)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # RAKSHAM/
PRODUCT = ROOT / "product"                          # Asli Awaaz service, screens, tests
ML = ROOT / "ml"
DETECTOR = ML / "live_detector"                     # numpy-only detector + demo + storage server
MODELS = ML / "models"                              # weights (git-ignored) + MODELS.md
DATA = ROOT / "data"
RECORDINGS = DATA / "recordings_awaaz"              # real recordings, consent files, manifests
GENERATED = DATA / "generated"                      # voice clones + manifest
SEHAJ = DATA / "sehaj_dataset"                      # labels.csv + audio (English + Hinglish)
CASES = ROOT / "cases"                              # saved calls (audio + analysis), local only
RESULTS = ROOT / "results"
