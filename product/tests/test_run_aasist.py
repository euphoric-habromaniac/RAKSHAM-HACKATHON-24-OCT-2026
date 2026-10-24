import csv
import json

import numpy as np
import pytest

from eval import run_aasist as R
from eval import summarise as S

PROTO = "\n".join(
    [f"LA_001 LA_E_{i:04d} - A07 spoof" for i in range(90)]
    + [f"LA_002 LA_E_{i:04d} - - bonafide" for i in range(1000, 1010)]
) + "\n"


def test_read_protocol(tmp_path):
    p = tmp_path / "p.txt"
    p.write_text(PROTO)
    items = R.read_protocol(p)
    assert len(items) == 100
    assert sum(l for _, l in items) == 10
    assert items[0] == ("LA_E_0000", 0)


def test_subset_stratified_and_deterministic(tmp_path):
    p = tmp_path / "p.txt"
    p.write_text(PROTO)
    items = R.read_protocol(p)
    s1, s2 = R.subset(items, 20, seed=3), R.subset(items, 20, seed=3)
    assert s1 == s2 and len(s1) == 20
    assert sum(l for _, l in s1) == 2  # 10 % bona fide kept
    b = R.subset(items, 20, seed=3, balanced=True)
    assert sum(l for _, l in b) == 10
    assert R.subset(items, None) == items


def test_pad_or_tile():
    x = np.arange(10, dtype=np.float32)
    assert len(R.pad_or_tile(x, 25)) == 25
    assert R.pad_or_tile(x, 25)[10] == 0  # repeats
    assert len(R.pad_or_tile(np.zeros(100000), R.NB_SAMP)) == R.NB_SAMP


def test_summarise(tmp_path):
    rng = np.random.default_rng(0)
    for name, shift in [("clean16k", 3.0), ("g711u", 1.0)]:
        with open(tmp_path / f"{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["utt_id", "label", "score"])
            for i, s in enumerate(rng.normal(shift, 1, 200)):
                w.writerow([f"b{i}", "bonafide", s])
            for i, s in enumerate(rng.normal(0, 1, 400)):
                w.writerow([f"s{i}", "spoof", s])
    text = S.summarise(tmp_path)
    assert "pretrained-model results without fine-tuning" in text
    assert "| clean16k | 200 | 400 |" in text
    lines = [l for l in text.splitlines() if l.startswith("| ")]
    assert lines[1].startswith("| clean16k") and lines[2].startswith("| g711u")


def test_end_to_end_with_fake_aasist_repo(tmp_path):
    """Builds a fake clovaai/aasist layout (config/, models/, weights) and runs the CLI."""
    torch = pytest.importorskip("torch")
    sf = pytest.importorskip("soundfile")
    repo = tmp_path / "aasist"
    (repo / "config").mkdir(parents=True)
    (repo / "models" / "weights").mkdir(parents=True)
    (repo / "models" / "Fake.py").write_text(
        "import torch, torch.nn as nn\n"
        "class Model(nn.Module):\n"
        "    def __init__(self, cfg):\n"
        "        super().__init__(); self.fc = nn.Linear(1, 2)\n"
        "    def forward(self, x):\n"
        "        h = x.abs().mean(dim=1, keepdim=True)\n"
        "        return h, self.fc(h)\n"
    )
    (repo / "config" / "AASIST.conf").write_text(json.dumps(
        {"model_path": "./models/weights/AASIST.pth", "model_config": {"architecture": "Fake"}}))
    sd = {"fc.weight": torch.tensor([[0.0], [10.0]]), "fc.bias": torch.zeros(2)}
    torch.save(sd, repo / "models" / "weights" / "AASIST.pth")

    audio = tmp_path / "audio"
    audio.mkdir()
    rng = np.random.default_rng(0)
    proto = []
    for i in range(20):
        label = i % 2
        amp = 0.5 if label else 0.05  # louder = "bonafide" for the fake model
        sf.write(str(audio / f"U{i}.wav"), (amp * rng.standard_normal(20000)).astype(np.float32), 16000)
        proto.append(f"S U{i} - A01 {'bonafide' if label else 'spoof'}")
    (tmp_path / "proto.txt").write_text("\n".join(proto) + "\n")

    out = tmp_path / "results" / "clean16k.csv"
    rc = R.main(["--aasist-repo", str(repo), "--model", "AASIST", "--protocol", str(tmp_path / "proto.txt"),
                 "--audio-dir", str(audio), "--device", "cpu", "--num-workers", "0", "--out", str(out)])
    assert rc == 0
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 20
    bona = [float(r["score"]) for r in rows if r["label"] == "bonafide"]
    spoof = [float(r["score"]) for r in rows if r["label"] == "spoof"]
    assert R.compute_eer(bona, spoof)[0] == 0.0
    # spoof logit appended as the last column; fake model: logit0 = 0*h + 0 = 0
    with open(out) as fh:
        assert next(csv.reader(fh)) == ["utt_id", "label", "score", "spoof_logit"]
    assert all(float(r["spoof_logit"]) == 0.0 for r in rows)
    # bonafide logit = 10*h, so score must still be the unchanged bona fide column
    assert all(float(r["score"]) > 0 for r in rows)


def test_make_subset_matches_run_subset(tmp_path):
    from eval import make_subset as M
    sf = pytest.importorskip("soundfile")
    audio = tmp_path / "flac"
    audio.mkdir()
    for utt, _ in R.read_protocol(_proto(tmp_path)):
        sf.write(str(audio / f"{utt}.flac"), np.zeros(1600, dtype=np.float32), 16000)
    out = tmp_path / "sub"
    assert M.main(["--protocol", str(_proto(tmp_path)), "--audio-dir", str(audio),
                   "--limit", "20", "--seed", "3", "--out", str(out)]) == 0
    want = {u for u, _ in R.subset(R.read_protocol(_proto(tmp_path)), 20, seed=3)}
    assert {p.stem for p in out.iterdir()} == want


def _proto(tmp_path):
    p = tmp_path / "p.txt"
    p.write_text(PROTO)
    return p
