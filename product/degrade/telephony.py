"""Simulate telephone-channel degradation for anti-spoofing evaluation.

Every condition produces a 16 kHz mono 16-bit WAV, because AASIST expects
16 kHz input. For the telephone conditions the signal is resampled to 8 kHz
(the narrowband telephone rate), passed through the codec (encode then decode
with ffmpeg), optionally impaired, and resampled back to 16 kHz. The content
above 4 kHz is therefore gone for good, as on a real narrowband call.

Conditions
----------
clean16k  only convert to 16 kHz mono WAV (no degradation, the control)
pstn8k    resample to 8 kHz and back (band-limit to 4 kHz, no codec)
g711u     G.711 mu-law
g711a     G.711 A-law
gsm       GSM 06.10 full rate (ffmpeg libgsm)
amrnb     AMR-NB 12.2 kbps (needs ffmpeg built with libopencore_amrnb)
opus8k    Opus 8 kbps, narrowband (ffmpeg libopus)
loss5     g711u + 5 % of 20 ms frames zeroed
loss10    g711u + 10 % of 20 ms frames zeroed
noise20   g711u + white noise at 20 dB SNR
noise10   g711u + white noise at 10 dB SNR

Packet loss model
-----------------
Frames of 20 ms (160 samples at 8 kHz) are replaced with silence. By default
loss is independent per frame (Bernoulli) at the requested rate. A bursty
Gilbert-Elliott two-state model is available through ``loss_burst`` (mean
burst length in frames, default 1.0 = independent): the chain has states
GOOD and BAD, every frame in BAD is lost, P(BAD->GOOD) = 1/burst and
P(GOOD->BAD) is chosen so the stationary loss rate equals the requested rate.
The shipped conditions use burst = 1.0; change ``Condition.loss_burst`` to
try bursts. No concealment (PLC) is applied, so this is a pessimistic model.

Noise is added after the codec at the stated SNR, measured against the mean
power of the decoded 8 kHz signal.

Determinism
-----------
Random choices use ``numpy.random.default_rng`` seeded from the base seed
and a CRC32 of the file's relative path, so reruns give identical output and
different files get different loss/noise patterns.

Dependencies: numpy and scipy are required. soundfile is used for file IO if
installed, otherwise ffmpeg is used. ffmpeg must be on PATH.
"""
from __future__ import annotations

import argparse
import functools
import math
import shutil
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import resample_poly

try:  # optional
    import soundfile as sf
except Exception:  # pragma: no cover - depends on environment
    sf = None

TARGET_SR = 16000
TEL_SR = 8000
FRAME_MS = 20
DEFAULT_SEED = 1234
AUDIO_EXTS = (".flac", ".wav")


@dataclass(frozen=True)
class Condition:
    name: str
    codec: Optional[str] = None  # None = no codec step
    telephone: bool = True  # False only for clean16k
    loss_rate: float = 0.0
    loss_burst: float = 1.0
    snr_db: Optional[float] = None
    description: str = ""


CONDITIONS = {
    c.name: c
    for c in [
        Condition("clean16k", telephone=False, description="16 kHz mono WAV only"),
        Condition("pstn8k", description="8 kHz band-limit and back"),
        Condition("g711u", codec="g711u", description="G.711 mu-law"),
        Condition("g711a", codec="g711a", description="G.711 A-law"),
        Condition("gsm", codec="gsm", description="GSM 06.10 full rate"),
        Condition("amrnb", codec="amrnb", description="AMR-NB 12.2 kbps"),
        Condition("opus8k", codec="opus", description="Opus 8 kbps narrowband"),
        Condition("loss5", codec="g711u", loss_rate=0.05, description="g711u + 5% frame loss"),
        Condition("loss10", codec="g711u", loss_rate=0.10, description="g711u + 10% frame loss"),
        Condition("noise20", codec="g711u", snr_db=20.0, description="g711u + white noise 20 dB SNR"),
        Condition("noise10", codec="g711u", snr_db=10.0, description="g711u + white noise 10 dB SNR"),
    ]
}

# codec -> (required ffmpeg encoder, ffmpeg args for the encode step, file suffix)
_CODECS = {
    "g711u": ("pcm_mulaw", ["-c:a", "pcm_mulaw"], ".wav"),
    "g711a": ("pcm_alaw", ["-c:a", "pcm_alaw"], ".wav"),
    "gsm": ("libgsm", ["-c:a", "libgsm", "-f", "gsm"], ".gsm"),
    "amrnb": ("libopencore_amrnb", ["-c:a", "libopencore_amrnb", "-b:a", "12.2k", "-f", "amr"], ".amr"),
    "opus": ("libopus", ["-c:a", "libopus", "-b:a", "8k", "-application", "voip", "-cutoff", "4000", "-f", "ogg"], ".opus"),
}

AMRNB_HINT = (
    "ffmpeg has no libopencore_amrnb encoder. On Colab/Ubuntu try: "
    "`apt-get install -y ffmpeg libopencore-amrnb0 libopencore-amrwb0`. "
    "If `ffmpeg -encoders | grep amr` is still empty, install a static ffmpeg build "
    "that includes libopencore-amrnb, or skip the amrnb condition."
)


class DegradeError(RuntimeError):
    """Raised for missing tools/encoders or failed ffmpeg calls."""


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------
def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise DegradeError("ffmpeg not found on PATH (Colab: `apt-get install -y ffmpeg`).")
    return exe


@functools.lru_cache(maxsize=1)
def available_encoders() -> frozenset:
    """Names of audio encoders reported by `ffmpeg -encoders`."""
    out = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        # lines look like: " A....D libgsm   libgsm GSM (codec gsm)"
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] == "A":
            names.add(parts[1])
    return frozenset(names)


def condition_available(name: str) -> bool:
    return not missing_requirements(name)


def missing_requirements(name: str) -> str:
    """Return an explanation of what is missing for a condition, or ''."""
    cond = get_condition(name)
    if shutil.which("ffmpeg") is None:
        return "ffmpeg not found on PATH."
    if cond.codec is None:
        return ""
    enc = _CODECS[cond.codec][0]
    if enc not in available_encoders():
        return AMRNB_HINT if cond.codec == "amrnb" else (
            f"ffmpeg lacks the `{enc}` encoder needed for condition '{name}' "
            "(Colab: `apt-get install -y ffmpeg`)."
        )
    return ""


def get_condition(name: str) -> Condition:
    try:
        return CONDITIONS[name]
    except KeyError:
        raise DegradeError(f"unknown condition '{name}'. Choose from: {', '.join(CONDITIONS)}") from None


def _run_ffmpeg(args: list) -> None:
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DegradeError(f"ffmpeg failed ({' '.join(cmd)}): {proc.stderr.strip()}")


# --------------------------------------------------------------------------
# audio IO
# --------------------------------------------------------------------------
def read_audio(path: Path) -> tuple:
    """Return (mono float32 array, sample rate)."""
    if sf is not None:
        try:
            x, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return x.mean(axis=1).astype(np.float32), int(sr)
        except Exception:
            pass  # fall through to ffmpeg
    proc = subprocess.run(
        [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-ac", "1", "-ar", str(TARGET_SR), "-f", "f32le", "pipe:1"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise DegradeError(f"ffmpeg could not read {path}: {proc.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(proc.stdout, dtype="<f4").copy(), TARGET_SR


def write_wav(path: Path, x: np.ndarray, sr: int) -> None:
    """Write mono 16-bit PCM WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(x, -1.0, 1.0).astype(np.float32)
    if sf is not None:
        sf.write(str(path), x, sr, subtype="PCM_16")
        return
    proc = subprocess.run(
        [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-c:a", "pcm_s16le", str(path)],
        input=x.astype("<f4").tobytes(), capture_output=True,
    )
    if proc.returncode != 0:
        raise DegradeError(f"ffmpeg could not write {path}: {proc.stderr.decode(errors='replace').strip()}")


# --------------------------------------------------------------------------
# signal processing
# --------------------------------------------------------------------------
def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32)
    g = math.gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def _fit_length(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.pad(x, (0, n - len(x)))


def codec_roundtrip(x8k: np.ndarray, codec: str) -> np.ndarray:
    """Encode and decode an 8 kHz mono signal with an ffmpeg codec; returns 8 kHz float32."""
    enc_name, enc_args, suffix = _CODECS[codec]
    if enc_name not in available_encoders():
        raise DegradeError(AMRNB_HINT if codec == "amrnb" else f"ffmpeg lacks encoder {enc_name}")
    with tempfile.TemporaryDirectory(prefix="degrade_") as tmp:
        tmp = Path(tmp)
        src, enc, dec = tmp / "in.wav", tmp / f"enc{suffix}", tmp / "dec.wav"
        write_wav(src, x8k, TEL_SR)
        _run_ffmpeg(["-i", str(src), "-ar", str(TEL_SR), "-ac", "1", *enc_args, str(enc)])
        _run_ffmpeg(["-i", str(enc), "-ar", str(TEL_SR), "-ac", "1", "-c:a", "pcm_s16le", str(dec)])
        y, sr = read_audio(dec)
    if sr != TEL_SR:  # should not happen, ffmpeg was told -ar 8000
        y = resample(y, sr, TEL_SR)
    return _fit_length(y, len(x8k))  # codecs may add delay/padding


def loss_mask(n_frames: int, rate: float, rng: np.random.Generator, burst: float = 1.0) -> np.ndarray:
    """Boolean array, True where a frame is lost.

    burst <= 1: independent (Bernoulli) loss. burst > 1: Gilbert-Elliott chain with
    mean burst length `burst` frames and stationary loss probability `rate`.
    """
    if rate <= 0 or n_frames == 0:
        return np.zeros(n_frames, dtype=bool)
    if rate >= 1.0:
        return np.ones(n_frames, dtype=bool)
    if burst <= 1.0:
        return rng.random(n_frames) < rate
    p_bg = 1.0 / burst
    p_gb = min(1.0, p_bg * rate / (1.0 - rate))
    u = rng.random(n_frames)
    lost = np.zeros(n_frames, dtype=bool)
    bad = rng.random() < rate  # start from the stationary distribution
    for i in range(n_frames):
        bad = (u[i] >= p_bg) if bad else (u[i] < p_gb)
        lost[i] = bad
    return lost


def apply_packet_loss(x8k: np.ndarray, rate: float, rng: np.random.Generator, burst: float = 1.0) -> np.ndarray:
    frame = TEL_SR * FRAME_MS // 1000
    n_frames = int(math.ceil(len(x8k) / frame))
    lost = loss_mask(n_frames, rate, rng, burst)
    y = x8k.copy()
    for i in np.flatnonzero(lost):
        y[i * frame:(i + 1) * frame] = 0.0
    return y


def add_white_noise(x: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    power = float(np.mean(x.astype(np.float64) ** 2))
    if power <= 0:
        return x.copy()
    sigma = math.sqrt(power / (10 ** (snr_db / 10)))
    return (x + rng.normal(0.0, sigma, size=x.shape)).astype(np.float32)


def seed_for(key: str, base_seed: int = DEFAULT_SEED) -> int:
    return (base_seed * 1_000_003 + zlib.crc32(key.encode("utf-8"))) % (2 ** 32)


def degrade_array(x: np.ndarray, sr: int, condition: str, seed_key: str = "",
                  base_seed: int = DEFAULT_SEED) -> np.ndarray:
    """Apply a condition to a mono float array; returns 16 kHz float32 with the
    same duration as the input."""
    cond = get_condition(condition)
    n_out = int(round(len(x) * TARGET_SR / sr))
    x16 = resample(x, sr, TARGET_SR)
    if not cond.telephone:
        return _fit_length(x16, n_out)
    rng = np.random.default_rng(seed_for(f"{condition}:{seed_key}", base_seed))
    x8 = resample(x, sr, TEL_SR)
    if cond.codec is not None:
        x8 = codec_roundtrip(x8, cond.codec)
    if cond.loss_rate > 0:
        x8 = apply_packet_loss(x8, cond.loss_rate, rng, cond.loss_burst)
    if cond.snr_db is not None:
        x8 = add_white_noise(x8, cond.snr_db, rng)
    y = resample(x8, TEL_SR, TARGET_SR)
    return _fit_length(np.clip(y, -1.0, 1.0), n_out)


def degrade_file(src: Path, dst: Path, condition: str, seed_key: Optional[str] = None,
                 base_seed: int = DEFAULT_SEED) -> None:
    x, sr = read_audio(src)
    y = degrade_array(x, sr, condition, seed_key if seed_key is not None else src.name, base_seed)
    write_wav(dst, y, TARGET_SR)


# --------------------------------------------------------------------------
# batch / CLI
# --------------------------------------------------------------------------
def _job(args: tuple) -> str:
    src, dst, condition, key, seed = args
    degrade_file(Path(src), Path(dst), condition, key, seed)
    return dst


def list_inputs(in_dir: Path) -> list:
    return sorted(p for p in in_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS)


def degrade_dir(in_dir: Path, out_dir: Path, condition: str, workers: int = 1,
                seed: int = DEFAULT_SEED, overwrite: bool = False) -> int:
    problem = missing_requirements(condition)
    if problem:
        raise DegradeError(problem)
    files = list_inputs(in_dir)
    if not files:
        raise DegradeError(f"no .flac/.wav files under {in_dir}")
    jobs = []
    for f in files:
        rel = f.relative_to(in_dir)
        dst = out_dir / rel.with_suffix(".wav")
        if dst.exists() and not overwrite:
            continue
        jobs.append((str(f), str(dst), condition, rel.as_posix(), seed))
    try:
        from tqdm import tqdm  # optional
    except Exception:
        def tqdm(it, **_kw):
            return it
    if workers <= 1:
        for j in tqdm(jobs, desc=condition):
            _job(j)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for _ in tqdm(ex.map(_job, jobs, chunksize=8), total=len(jobs), desc=condition):
                pass
    print(f"{condition}: wrote {len(jobs)} files to {out_dir} ({len(files) - len(jobs)} already present)")
    return len(jobs)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m degrade.telephony",
                                 description="Apply a telephone-channel degradation to a directory of flac/wav files.")
    ap.add_argument("--in", dest="in_dir", type=Path, required=True)
    ap.add_argument("--out", dest="out_dir", type=Path, required=True)
    ap.add_argument("--condition", required=True, choices=list(CONDITIONS))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--overwrite", action="store_true", help="redo files that already exist in --out")
    a = ap.parse_args(argv)
    try:
        degrade_dir(a.in_dir, a.out_dir, a.condition, a.workers, a.seed, a.overwrite)
    except DegradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
