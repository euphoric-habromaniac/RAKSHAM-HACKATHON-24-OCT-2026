"""Minimal PCM helpers (pure Python, 16-bit mono little-endian)."""
from __future__ import annotations

import sys
from array import array

TARGET_RATE = 16000


def resample_8k_to_16k(pcm: bytes) -> bytes:
    """Double the sample rate by linear interpolation.

    Telephony audio is 8 kHz; the models expect 16 kHz. Upsampling adds no
    information above 4 kHz. Production should use a polyphase resampler
    (scipy.signal.resample_poly or torchaudio); this keeps the service
    dependency-free.
    """
    src = array("h")
    src.frombytes(pcm)
    if sys.byteorder == "big":  # pragma: no cover
        src.byteswap()
    out = array("h", bytes(len(src) * 4))
    n = len(src)
    for i in range(n):
        cur = src[i]
        nxt = src[i + 1] if i + 1 < n else cur
        out[2 * i] = cur
        out[2 * i + 1] = (cur + nxt) // 2
    if sys.byteorder == "big":  # pragma: no cover
        out.byteswap()
    return out.tobytes()


def to_16k(pcm: bytes, sample_rate: int) -> bytes:
    if sample_rate == TARGET_RATE:
        return pcm
    if sample_rate == 8000:
        return resample_8k_to_16k(pcm)
    raise ValueError(f"unsupported sample rate {sample_rate}")
