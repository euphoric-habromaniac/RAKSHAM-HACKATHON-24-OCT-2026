"""ASLI_L2_MODEL opt-in switch for the real L2 scorer in create_app."""
import numpy as np
import pytest

from service.api import create_app
from service.scorers import AasistSpoofScorer, MockSpoofScorer


def _app(tmp_path):
    return create_app(evidence_path=str(tmp_path / "ev.jsonl"))


def test_env_unset_uses_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("ASLI_L2_MODEL", raising=False)
    assert isinstance(_app(tmp_path).state.engine.l2, MockSpoofScorer)


def test_env_set_uses_aasist_torchscript(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")

    class Stub(torch.nn.Module):
        def forward(self, x):
            return torch.tensor([[2.0, -2.0]])

    path = tmp_path / "stub_l2.pt"
    torch.jit.script(Stub()).save(str(path))
    monkeypatch.setenv("ASLI_L2_MODEL", str(path))
    monkeypatch.delenv("ASLI_L2_DEVICE", raising=False)

    l2 = _app(tmp_path).state.engine.l2
    assert isinstance(l2, AasistSpoofScorer)
    assert l2.model_version == "aasist-ts:stub_l2.pt"
    assert l2.device == "cpu"
    pcm = (np.random.RandomState(0).randn(16000) * 1000).astype(np.int16)
    assert l2.score(pcm, 16000, {}) > 0.9


def test_env_set_to_missing_path_raises(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setenv("ASLI_L2_MODEL", str(tmp_path / "nope.pt"))
    with pytest.raises(RuntimeError, match="ASLI_L2_MODEL"):
        _app(tmp_path)


def test_env_set_to_invalid_file_raises(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    bad = tmp_path / "bad.pt"
    bad.write_bytes(b"not a torchscript model")
    monkeypatch.setenv("ASLI_L2_MODEL", str(bad))
    with pytest.raises(RuntimeError, match="could not be loaded"):
        _app(tmp_path)


def test_env_set_with_placeholder_l2_warns(tmp_path, monkeypatch, caplog):
    torch = pytest.importorskip("torch")

    class Stub(torch.nn.Module):
        def forward(self, x):
            return torch.tensor([[2.0, -2.0]])

    path = tmp_path / "stub_l2.pt"
    torch.jit.script(Stub()).save(str(path))
    monkeypatch.setenv("ASLI_L2_MODEL", str(path))
    with caplog.at_level("WARNING", logger="service.api"):
        _app(tmp_path)  # default config.json: l2 is still a placeholder
    assert "config.calibrated.json" in caplog.text
