import numpy as np
import pytest
import soundfile as sf

from degrade import telephony as T

SR = 16000
pytestmark = pytest.mark.skipif(not T.shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def signal():
    rng = np.random.default_rng(0)
    t = np.arange(2 * SR) / SR
    # speech-band tone + a 6 kHz tone (must be removed by 8 kHz sampling) + a little noise
    x = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 6000 * t) + 0.02 * rng.standard_normal(len(t))
    return x.astype(np.float32)


@pytest.fixture(scope="module")
def src_wav(tmp_path_factory, signal):
    p = tmp_path_factory.mktemp("in") / "sig.wav"
    sf.write(str(p), signal, SR, subtype="PCM_16")
    return p


def available():
    return [c for c in T.CONDITIONS if T.condition_available(c)]


@pytest.mark.parametrize("cond", list(T.CONDITIONS))
def test_condition_output_format(cond, src_wav, signal, tmp_path):
    if not T.condition_available(cond):
        pytest.skip(f"condition {cond}: {T.missing_requirements(cond)}")
    dst = tmp_path / "out.wav"
    T.degrade_file(src_wav, dst, cond)
    info = sf.info(str(dst))
    assert info.samplerate == 16000
    assert info.channels == 1
    assert abs(info.frames - len(signal)) <= 0.01 * len(signal)
    y, _ = sf.read(str(dst))
    assert np.isfinite(y).all() and np.abs(y).max() <= 1.0
    assert np.abs(y).max() > 0.01  # not silent


def _hf_energy_fraction(x, cutoff=4000):
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    return spec[freqs > cutoff].sum() / spec.sum()


def test_pstn8k_removes_energy_above_4k(src_wav, signal, tmp_path):
    dst = tmp_path / "o.wav"
    T.degrade_file(src_wav, dst, "pstn8k")
    y, _ = sf.read(str(dst))
    assert _hf_energy_fraction(signal) > 0.1
    assert _hf_energy_fraction(y) < 0.001


def test_clean16k_keeps_signal(src_wav, signal, tmp_path):
    dst = tmp_path / "o.wav"
    T.degrade_file(src_wav, dst, "clean16k")
    y, _ = sf.read(str(dst))
    assert np.max(np.abs(y - signal)) < 1e-3  # 16-bit quantisation only


def test_deterministic(src_wav, tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    T.degrade_file(src_wav, a, "loss10", seed_key="x")
    T.degrade_file(src_wav, b, "loss10", seed_key="x")
    assert a.read_bytes() == b.read_bytes()
    c = tmp_path / "c.wav"
    T.degrade_file(src_wav, c, "loss10", seed_key="other")
    assert a.read_bytes() != c.read_bytes()


def test_packet_loss_rate_and_frames():
    rng = np.random.default_rng(0)
    x = np.ones(8000 * 200, dtype=np.float32)  # 200 s
    y = T.apply_packet_loss(x, 0.10, rng)
    frames = y.reshape(-1, 160)
    zeroed = (frames.max(axis=1) == 0)
    assert (frames.min(axis=1) == frames.max(axis=1)).all()  # whole frames only
    assert zeroed.mean() == pytest.approx(0.10, abs=0.02)


def test_gilbert_elliott_is_bursty_with_same_rate():
    rng = np.random.default_rng(0)
    iid = T.loss_mask(20000, 0.1, rng, burst=1.0)
    ge = T.loss_mask(20000, 0.1, np.random.default_rng(0), burst=5.0)
    assert ge.mean() == pytest.approx(0.1, abs=0.02)

    def mean_burst(m):
        runs, n = [], 0
        for v in m:
            if v:
                n += 1
            elif n:
                runs.append(n); n = 0
        return np.mean(runs)
    assert mean_burst(ge) > 2 * mean_burst(iid)


def test_noise_snr():
    rng = np.random.default_rng(0)
    x = (0.3 * np.sin(2 * np.pi * 300 * np.arange(80000) / 8000)).astype(np.float32)
    y = T.add_white_noise(x, 20.0, rng)
    snr = 10 * np.log10(np.mean(x ** 2) / np.mean((y - x) ** 2))
    assert snr == pytest.approx(20.0, abs=0.5)


def test_amrnb_missing_gives_clear_error(src_wav, tmp_path, monkeypatch):
    monkeypatch.setattr(T, "available_encoders", lambda: frozenset({"pcm_mulaw"}))
    assert not T.condition_available("amrnb")
    with pytest.raises(T.DegradeError, match="apt-get install"):
        T.degrade_dir(src_wav.parent, tmp_path / "o", "amrnb")


def test_cli_directory(src_wav, tmp_path):
    out = tmp_path / "out"
    rc = T.main(["--in", str(src_wav.parent), "--out", str(out), "--condition", "g711u", "--workers", "2"])
    assert rc == 0
    assert sf.info(str(out / "sig.wav")).samplerate == 16000


def test_works_without_soundfile(src_wav, signal, tmp_path, monkeypatch):
    monkeypatch.setattr(T, "sf", None)  # force the ffmpeg IO path
    dst = tmp_path / "o.wav"
    T.degrade_file(src_wav, dst, "gsm" if T.condition_available("gsm") else "g711u")
    monkeypatch.undo()
    info = sf.info(str(dst))
    assert info.samplerate == 16000 and info.channels == 1
    assert abs(info.frames - len(signal)) <= 0.01 * len(signal)


def test_loss_mask_total_loss_with_bursts_does_not_divide_by_zero():
    rng = np.random.default_rng(0)
    assert T.loss_mask(50, 1.0, rng, burst=4.0).all()
    assert T.loss_mask(50, 1.0, rng, burst=1.0).all()
