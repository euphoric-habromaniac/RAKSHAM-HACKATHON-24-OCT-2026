"""Shared helpers for the recorder tests (stdlib only)."""
import io
import math
import struct
import wave

FIELDS = {"name": "Test Person", "age_band": "25-34", "gender": "", "accent_group": "Hindi-belt", "device": "laptop mic",
          "consent_language": "en", "allow_recording": True, "allow_spoof_testing": True, "allow_voice_cloning": False}


def make_wav(seconds=2.0, rate=16000, channels=1, width=2, freq=220.0, amp=0.3) -> bytes:
    """A sine WAV as bytes (PCM, `width` bytes per sample)."""
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = amp * math.sin(2 * math.pi * freq * i / rate)
            for _ in range(channels):
                frames += struct.pack("<h", int(v * 32767)) if width == 2 else struct.pack("<B", int(128 + v * 127))
        w.writeframes(bytes(frames))
    return buf.getvalue()
