"""Scorer interfaces, deterministic mocks, and lazily-imported real adapters.

Contract for raw scores (calibration.py maps these to probabilities):
  L1  cosine similarity to the enrolled embedding, higher = more similar.
  L2  synthetic-speech score in [0, 1], higher = more likely synthetic.
Audio is 16-bit mono little-endian PCM at 16 kHz by the time it gets here.

The real adapters import their heavy dependencies inside methods, so this
module imports cleanly on a machine without torch, speechbrain or
faster-whisper. They are not exercised by the test suite.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable


class ScorerError(RuntimeError):
    """Raised by a scorer when it cannot produce a score."""


@runtime_checkable
class SpeakerScorer(Protocol):
    model_version: str

    def score(self, customer_id: str, pcm: bytes, sample_rate: int, meta: Mapping[str, Any]) -> float: ...


@runtime_checkable
class SpoofScorer(Protocol):
    model_version: str

    def score(self, pcm: bytes, sample_rate: int, meta: Mapping[str, Any]) -> float: ...


@runtime_checkable
class ASR(Protocol):
    model_version: str

    def transcribe(self, pcm: bytes, sample_rate: int, meta: Mapping[str, Any]) -> str: ...


# --------------------------------------------------------------------- mocks
class MockSpeakerScorer:
    """Returns metadata['mock_l1_cosine'] (default 0.80). 'mock_error' == 'l1' raises."""

    model_version = "mock-l1-0"

    def score(self, customer_id, pcm, sample_rate, meta):
        if meta.get("mock_error") == "l1":
            raise ScorerError("mock L1 failure")
        return float(meta.get("mock_l1_cosine", 0.80))


class MockSpoofScorer:
    """Returns metadata['mock_l2_spoof'] (default 0.05). 'mock_error' == 'l2' raises."""

    model_version = "mock-l2-0"

    def score(self, pcm, sample_rate, meta):
        if meta.get("mock_error") == "l2":
            raise ScorerError("mock L2 failure")
        return float(meta.get("mock_l2_spoof", 0.05))


class MockASR:
    """Returns metadata['mock_asr_text'] (default ''). 'mock_error' == 'asr' raises."""

    model_version = "mock-asr-0"

    def transcribe(self, pcm, sample_rate, meta):
        if meta.get("mock_error") == "asr":
            raise ScorerError("mock ASR failure")
        return str(meta.get("mock_asr_text", ""))


# ------------------------------------------------------------ real adapters
def _pcm_to_float32(pcm: bytes):
    import numpy as np  # lazy

    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class SpeechBrainEcapaSpeakerScorer:
    """ECAPA-TDNN speaker verification via SpeechBrain.

    enrolled_lookup(customer_id) must return the enrolled embedding as a
    sequence of floats (192-dim for spkrec-ecapa-voxceleb), produced by the
    same model at enrolment time.
    """

    def __init__(
        self,
        enrolled_lookup: Callable[[str], Sequence[float]],
        source: str = "speechbrain/spkrec-ecapa-voxceleb",
        savedir: str = "pretrained_models/spkrec-ecapa-voxceleb",
        device: str = "cpu",
    ):
        self.enrolled_lookup = enrolled_lookup
        self.source, self.savedir, self.device = source, savedir, device
        self.model_version = f"speechbrain-ecapa:{source}"
        self._clf = None

    def _load(self):
        if self._clf is None:
            try:
                try:
                    from speechbrain.inference.speaker import EncoderClassifier
                except ImportError:  # older SpeechBrain
                    from speechbrain.pretrained import EncoderClassifier  # type: ignore
            except ImportError as exc:
                raise ScorerError("speechbrain is not installed (see requirements-ml.txt)") from exc
            self._clf = EncoderClassifier.from_hparams(
                source=self.source, savedir=self.savedir, run_opts={"device": self.device}
            )
        return self._clf

    def score(self, customer_id, pcm, sample_rate, meta):
        import torch  # lazy

        clf = self._load()
        wav = torch.from_numpy(_pcm_to_float32(pcm)).unsqueeze(0)
        emb = clf.encode_batch(wav).squeeze()
        enrolled = torch.tensor(list(self.enrolled_lookup(customer_id)), dtype=emb.dtype)
        return float(torch.nn.functional.cosine_similarity(emb, enrolled, dim=0))


# Class order of the AASIST output logits. This is the AASIST repo convention and the one
# eval/run_aasist.py and eval/train_degraded.py use: index 0 = spoof, index 1 = bona fide.
# Exported checkpoints used by the service must follow it (or pass spoof_index explicitly).
AASIST_LOGIT_ORDER = ("spoof", "bonafide")
AASIST_SPOOF_INDEX = AASIST_LOGIT_ORDER.index("spoof")


def spoof_probability(logits: Sequence[float], spoof_index: int = AASIST_SPOOF_INDEX) -> float:
    """Softmax probability of the spoof class from one row of two logits."""
    if len(logits) != 2 or spoof_index not in (0, 1):
        raise ScorerError(f"expected two logits and spoof_index 0 or 1, got {len(logits)} logits, index {spoof_index}")
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    return exps[spoof_index] / sum(exps)


class AasistSpoofScorer:
    """XLS-R front end + AASIST back end, loaded as an exported TorchScript module.

    The module must take a [1, T] float32 16 kHz waveform and return [1, 2]
    logits in AASIST order, (spoof, bona fide); see AASIST_LOGIT_ORDER. The score is the
    softmax probability of the spoof class, taken at ``spoof_index``. Exporting the
    checkpoint is done outside this repo.
    """

    def __init__(self, model_path: str, device: str = "cpu", model_version: str = "xlsr-aasist:unversioned",
                 spoof_index: int = AASIST_SPOOF_INDEX):
        self.model_path, self.device = model_path, device
        self.model_version = model_version
        self.spoof_index = spoof_index
        self._model = None

    def load(self):
        if self._model is None:
            try:
                import torch
            except ImportError as exc:
                raise ScorerError("torch is not installed (see requirements-ml.txt)") from exc
            self._model = torch.jit.load(self.model_path, map_location=self.device).eval()
        return self._model

    def score(self, pcm, sample_rate, meta):
        import torch  # lazy

        model = self.load()
        wav = torch.from_numpy(_pcm_to_float32(pcm)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            logits = model(wav)
        return spoof_probability(logits[0].float().tolist(), self.spoof_index)


class FasterWhisperASR:
    """faster-whisper transcription (CTranslate2). Language is auto-detected."""

    def __init__(self, model_size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_size, self.device, self.compute_type = model_size, device, compute_type
        self.model_version = f"faster-whisper:{model_size}"
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ScorerError("faster-whisper is not installed (see requirements-ml.txt)") from exc
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, pcm, sample_rate, meta):
        model = self._load()
        segments, _info = model.transcribe(_pcm_to_float32(pcm), beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip()
