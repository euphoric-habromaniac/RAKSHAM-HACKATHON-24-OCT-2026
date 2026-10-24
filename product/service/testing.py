"""Helpers shared by tests and the simulator."""
from __future__ import annotations

import base64
import math
import struct


class FakeClock:
    """Manual clock. Call advance(seconds) to move time."""

    def __init__(self, start: float = 1_800_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def tone_b64(seconds: float = 0.5, sample_rate: int = 8000, freq: float = 220.0) -> str:
    """A short sine tone as base64 16-bit PCM, enough to exercise the audio path."""
    n = int(seconds * sample_rate)
    pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))) for i in range(n))
    return base64.b64encode(pcm).decode()
