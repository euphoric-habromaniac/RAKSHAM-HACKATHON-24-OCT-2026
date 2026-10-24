"""The live detector as an opt-in L2 scorer. Needs only numpy; sample-audio tests skip if the demo clips are absent."""
import wave
from pathlib import Path

import numpy as np
import pytest

from service.live_scorer import LiveDetectorSpoofScorer
from service.scorers import ScorerError

SAMPLES = Path(__file__).resolve().parents[2] / "ml" / "live_detector" / "demo" / "samples"


def _pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        return w.readframes(w.getnframes())


def test_noise_has_no_speech_so_scorer_raises():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(32000) * 3000).astype("<i2").tobytes()
    with pytest.raises(ScorerError):
        LiveDetectorSpoofScorer().score(noise, 16000, {})


def test_wrong_sample_rate_is_rejected():
    with pytest.raises(ScorerError):
        LiveDetectorSpoofScorer().score(b"\x00\x00" * 8000, 8000, {})


def test_missing_model_fails_to_load(tmp_path):
    with pytest.raises(ScorerError):
        LiveDetectorSpoofScorer(model_path=str(tmp_path / "nope.npz")).load()


@pytest.mark.skipif(not (SAMPLES / "vukqxv0v_047_real.wav").exists(), reason="demo sample clips not present")
def test_real_scores_low_and_fake_scores_high():
    scorer = LiveDetectorSpoofScorer()
    real = scorer.score(_pcm(SAMPLES / "vukqxv0v_047_real.wav"), 16000, {})
    fake = scorer.score(_pcm(SAMPLES / "vukqxv0v_047_fake.wav"), 16000, {})
    assert 0.0 <= real < 0.5 < fake <= 1.0


def test_env_opt_in_returns_live_scorer(monkeypatch):
    from service import api

    monkeypatch.setenv("ASLI_L2_BACKEND", "live")
    scorer = api._l2_from_env()
    assert isinstance(scorer, LiveDetectorSpoofScorer)
    assert scorer.model_version.startswith("live-detector:")
    monkeypatch.delenv("ASLI_L2_BACKEND")
    assert api._l2_from_env() is None
