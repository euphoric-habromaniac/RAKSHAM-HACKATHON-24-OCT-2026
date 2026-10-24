"""Opt-in L2 adapter: the numpy-only live detector (ml/live_detector) as a SpoofScorer.

Enable with ASLI_L2_BACKEND=live (optionally ASLI_L2_LIVE_MODEL=<path to a model .npz>). Needs only numpy.

Raw score contract (see scorers.py): a float in [0, 1], higher = more likely synthetic.
Here: 1 - mean P(real) over the 0.5 s windows (hop 0.25 s) that contain speech.
No speech in the audio raises ScorerError, so the engine falls back to Step up (fail-open) instead of guessing.
The detector only knows its enrolled voices and its training cloner; limits apply to enrolled voices.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping, Optional

from .scorers import ScorerError

_REPO = Path(__file__).resolve().parents[2]          # RAKSHAM/
_DET_DIR = _REPO / "ml" / "live_detector"
_DEFAULT_MODEL = _DET_DIR / "model_0p5s.npz"


def _load_detector_module():
    spec = importlib.util.spec_from_file_location("raksham_live_detector", _DET_DIR / "detector.py")
    if spec is None or spec.loader is None:
        raise ScorerError(f"live detector not found under {_DET_DIR}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LiveDetectorSpoofScorer:
    def __init__(self, model_path: Optional[str] = None, model_version: Optional[str] = None):
        self.model_path = Path(model_path) if model_path else _DEFAULT_MODEL
        self.model_version = model_version or f"live-detector:{self.model_path.name}"
        self._mod = None
        self._det = None

    def load(self) -> None:
        if not self.model_path.is_file():
            raise ScorerError(f"live detector model not found: {self.model_path}")
        self._mod = _load_detector_module()
        self._det = self._mod.Detector(str(self.model_path))

    def score(self, pcm: bytes, sample_rate: int, meta: Mapping[str, Any]) -> float:
        import numpy as np  # lazy, like the other adapters

        if sample_rate != 16000:
            raise ScorerError(f"live detector needs 16 kHz audio, got {sample_rate}")
        if self._det is None:
            self.load()
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        win = self._det.win
        probs = []
        for start in range(0, len(x) - win + 1, win // 2):
            w = x[start:start + win]
            if self._mod.has_speech(w):
                probs.append(self._det.score(w))
        if not probs:
            raise ScorerError("live detector: no window in this audio contains speech")
        return float(1.0 - np.mean(probs))
