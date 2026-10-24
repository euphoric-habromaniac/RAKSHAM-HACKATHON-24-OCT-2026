"""Export the pretrained clovaai AASIST model as a TorchScript module for service.scorers.AasistSpoofScorer.

The exported module takes a float32 waveform [1, T] (16 kHz mono) and returns [1, 2]
logits in (spoof, bonafide) order, the same order eval/run_aasist.py scores with
(it uses column 1 = bonafide). Input is trimmed to the first NB_SAMP (64600) samples, or tiled
up to NB_SAMP, exactly like eval.run_aasist.pad_or_tile, so scores match that script.

Usage (from the repo root):
    .venv\\Scripts\\python.exe tools/export_aasist_torchscript.py --check
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from importlib import import_module
from pathlib import Path

import torch
from torch import Tensor, nn

ROOT = Path(__file__).resolve().parent.parent
NB_SAMP = 64600


class AasistTS(nn.Module):
    """[1, T] float32 -> [1, 2] logits (spoof, bonafide)."""

    def __init__(self, inner: nn.Module):
        super().__init__()
        self.inner = inner  # a traced module taking [1, NB_SAMP]
        self.nb_samp = NB_SAMP  # TorchScript cannot read module globals

    def forward(self, x: Tensor) -> Tensor:
        x = x.reshape(1, -1)
        n = x.shape[1]
        if n == 0:
            raise ValueError("empty waveform")
        if n >= self.nb_samp:
            x = x[:, :self.nb_samp]
        else:
            reps = self.nb_samp // n + 1
            x = x.repeat(1, reps)[:, :self.nb_samp]
        return self.inner(x)


class _Logits(nn.Module):
    """Eager wrapper dropping the embedding output of AASIST's (last_hidden, output)."""

    def __init__(self, model: nn.Module):
        super().__init__()
        self.model = model

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)[1]


def load_model(aasist_repo: Path, weights: Path, device: torch.device) -> nn.Module:
    repo = aasist_repo.resolve()
    with open(repo / "config" / "AASIST.conf", "r") as f:
        model_config = json.loads(f.read())["model_config"]
    sys.path.insert(0, str(repo))
    module = import_module("models.{}".format(model_config["architecture"]))
    model = getattr(module, "Model")(model_config).to(device)
    model.load_state_dict(torch.load(weights, map_location=device))
    model.eval()
    return model


def export(model: nn.Module, device: torch.device) -> torch.jit.ScriptModule:
    logits = _Logits(model).eval()
    example = torch.randn(1, NB_SAMP, device=device)
    with torch.no_grad():
        traced = torch.jit.trace(logits, example, check_trace=False)
        return torch.jit.script(AasistTS(traced).eval())


def check(ts, model: nn.Module, device: torch.device, flac_dir: Path, n: int = 3) -> float:
    import soundfile as sf

    sys.path.insert(0, str(ROOT))
    from eval.run_aasist import pad_or_tile

    files = sorted(flac_dir.glob("*.flac"))
    if not files:
        raise FileNotFoundError(f"no flac files in {flac_dir}")
    picks = random.Random(0).sample(files, min(n, len(files)))
    worst = 0.0
    for p in picks:
        x, sr = sf.read(str(p), dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        ref_in = torch.from_numpy(pad_or_tile(x).copy()).unsqueeze(0).to(device)
        with torch.no_grad():
            ref = model(ref_in)[1]
            got = ts(torch.from_numpy(x.copy()).unsqueeze(0).to(device))
        d = float((ref - got).abs().max())
        worst = max(worst, d)
        print(f"{p.name}: eager(spoof,bona)={ref[0].tolist()} ts={got[0].tolist()} absdiff={d:.2e}")
    print(f"max abs diff = {worst:.3e} ({'OK' if worst < 1e-3 else 'FAIL'}, tol 1e-3)")
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aasist-repo", type=Path, default=ROOT / "aasist")
    ap.add_argument("--weights", type=Path, default=ROOT / "aasist" / "models" / "weights" / "AASIST.pth")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "weights" / "aasist_ts.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--check", action="store_true",
                    help="compare against the eager model on 3 clips from data/raw/LA/subset5000/flac")
    ap.add_argument("--flac-dir", type=Path, default=ROOT / "data" / "raw" / "LA" / "subset5000" / "flac")
    a = ap.parse_args(argv)

    device = torch.device(a.device)
    model = load_model(a.aasist_repo, a.weights, device)
    ts = export(model, device)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    ts.save(str(a.out))
    print(f"saved {a.out} ({a.out.stat().st_size / 1e6:.2f} MB); output order = (spoof, bonafide)")

    if a.check:
        loaded = torch.jit.load(str(a.out), map_location=device).eval()
        if check(loaded, model, device, a.flac_dir) >= 1e-3:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
