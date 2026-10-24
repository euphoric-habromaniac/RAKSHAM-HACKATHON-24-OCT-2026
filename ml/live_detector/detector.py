"""Live real-vs-fake voice detector (Yash / Kushagra / Pranjal). NumPy only - no librosa/sklearn/TF needed.

    from detector import Detector
    d = Detector("model_0p5s.npz")          # window length is stored in the model
    d.score(x)       # x: mono float32 16 kHz, >= d.win samples -> P(real) of the LAST window
    d.stream(chunk)  # feed audio chunks of any size; returns {'label','p_real','silent'} per call, ~every 0.25 s
"""
import numpy as np

SR, N_FFT, HOP, N_MELS, N_MFCC = 16000, 512, 160, 64, 20
SILENCE_RMS = 0.002


def _mel_fb():
    hz = lambda m: 700 * (10 ** (m / 2595) - 1)
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    pts = hz(np.linspace(mel(50), mel(8000), N_MELS + 2))
    bins = np.fft.rfftfreq(N_FFT, 1 / SR)
    fb = np.zeros((N_MELS, len(bins)))
    for i in range(N_MELS):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.maximum(0, np.minimum((bins - lo) / (c - lo), (hi - bins) / (hi - c)))
    return fb.astype(np.float32)


def _dct():
    n = np.arange(N_MELS)
    d = np.sqrt(2 / N_MELS) * np.cos(np.pi * np.arange(N_MFCC)[:, None] * (2 * n[None] + 1) / (2 * N_MELS))
    d[0] /= np.sqrt(2)
    return d.astype(np.float32)


_FB, _DCT, _WIN = _mel_fb(), _dct(), np.hanning(N_FFT).astype(np.float32)


def features(x):
    """251-d level-invariant feature vector for one window (mono float32, 16 kHz)."""
    x = np.asarray(x, np.float32)
    x = x - x.mean()
    xp = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    nfr = 1 + (len(xp) - N_FFT) // HOP
    frames = xp[np.arange(N_FFT)[None] + HOP * np.arange(nfr)[:, None]] * _WIN
    S = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    mel = 10 * np.log10(S @ _FB.T + 1e-10)
    mel = mel - np.percentile(mel, 95)
    mf = mel @ _DCT.T
    return np.concatenate([mel.mean(0), mel.std(0), np.percentile(mel, 10, axis=0),
                           mf[:, 1:].mean(0), mf.std(0), np.diff(mf, axis=0).std(0)]).astype(np.float32)


def has_speech(x, min_voiced=0.08):
    """True if the window contains voiced speech (pitch-like periodicity, 70-400 Hz), at any loudness.
    Noise and rumble are not periodic with a pitch dip; a steady hum has a constant pitch and little energy above 800 Hz."""
    x = np.asarray(x, np.float32)
    L, hop = 400, 160
    n = (len(x) - L) // hop + 1
    if n < 1:
        return False
    fr = x[np.arange(L)[None] + hop * np.arange(n)[:, None]]
    fr = fr - fr.mean(1, keepdims=True)
    e = np.sqrt((fr ** 2).mean(1))
    P = np.abs(np.fft.rfft(fr, n=1024, axis=1)) ** 2
    ac = np.fft.irfft(P, axis=1)[:, :231]
    neg = ac[:, 1:] < 0
    first = np.where(neg.any(1), neg.argmax(1) + 1, 999)             # first dip: smooth noise/rumble never dips
    lags = np.arange(231)[None]
    masked = np.where((lags >= np.maximum(first, 40)[:, None]), ac, 0)
    peak, lag = masked.max(1), masked.argmax(1)
    r = peak / (ac[:, 0] + 1e-9)
    hf = P[:, 52:].sum(1) / (P.sum(1) + 1e-9)                         # energy above ~800 Hz
    voiced = (r > 0.4) & (hf > 0.02) & (e > SILENCE_RMS)
    if float(voiced.mean()) < min_voiced:
        return False
    if voiced.sum() >= 5 and float(hf[voiced].mean()) < 0.15:         # hum-like: little HF -> demand a moving pitch
        lv = lag[voiced]
        return float((np.abs(lv - np.median(lv)) <= 4).mean()) < 0.75
    return True


def is_silent(x):
    return not has_speech(x)


class Detector:
    def __init__(self, path):
        m = np.load(path)
        self.win = int(m["win"]); self.mu, self.sd = m["mu"], m["sd"]
        self.layers = [(m[f"W{i}"], m[f"b{i}"]) for i in range(int(m["n_layers"]))]
        self.buf = np.zeros(0, np.float32); self.ema = None; self._since = 0; self._gap = 0

    def _p_real(self, f):
        a = (f - self.mu) / self.sd
        for i, (W, b) in enumerate(self.layers):
            a = a @ W + b
            if i < len(self.layers) - 1:
                a = np.maximum(a, 0)
        return float(1 / (1 + np.exp(-a.ravel()[0])))

    def score(self, x):
        x = np.asarray(x, np.float32)[-self.win:]
        return self._p_real(features(x))

    def stream(self, chunk, hop=4000, smooth=0.5):
        self.buf = np.r_[self.buf, np.asarray(chunk, np.float32)][-self.win * 2:]
        self._since += len(chunk)
        if len(self.buf) < self.win or self._since < hop:
            return None
        self._since = 0
        w = self.buf[-self.win:]
        if is_silent(w):
            self._gap += hop
            if self.ema is not None and self._gap <= 16000:      # brief gap inside a sentence: keep the verdict
                return {"label": "real" if self.ema > 0.5 else "FAKE", "p_real": round(self.ema, 3), "silent": True}
            self.ema = None
            return {"label": "no speech", "p_real": None, "silent": True}
        self._gap = 0
        p = self.score(w)
        self.ema = p if self.ema is None else smooth * p + (1 - smooth) * self.ema
        return {"label": "real" if self.ema > 0.5 else "FAKE", "p_real": round(self.ema, 3), "silent": False}
