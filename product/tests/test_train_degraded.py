import os

import numpy as np
import pytest
import soundfile as sf

torch = pytest.importorskip("torch")

from eval import gpu_lock as G  # noqa: E402
from eval import train_degraded as T  # noqa: E402


def toy(tmp_path, n=32):
    conds = ["clean16k", "g711u"]
    items = T.write_toy_corpus(tmp_path, conds, n)
    sources = {c: tmp_path / c for c in conds}
    return items, sources, T.make_loader(T.MixDataset(items, sources, max_len=4000), 8, True, 0)


def test_dry_run_ok(capsys):
    assert T.main(["--dry-run"]) == 0
    assert "dry-run OK" in capsys.readouterr().out


def test_resume_continues_and_budget_stops(tmp_path):
    items, sources, loader = toy(tmp_path)
    val = T.make_loader(T.MixDataset(items, sources, max_len=4000), 8, False, 0)
    dev, ckpt = torch.device("cpu"), tmp_path / "m.pth"
    T.seed_everything(0)
    T.train(T.make_dummy_model(), loader, dev, 2, 3e-3, val_loader=val, out_path=ckpt, log=lambda m: None)
    assert ckpt.exists() and T.resume_path(ckpt).exists()
    msgs = []
    hist = T.train(T.make_dummy_model(), loader, dev, 4, 3e-3, val_loader=val, out_path=ckpt,
                   resume=True, log=msgs.append)
    assert len(hist["loss"]) == 4 and any("resumed" in m and "epoch 2" in m for m in msgs)
    # zero budget: stops before any step, still leaves weights + resume file, reports why
    ckpt2 = tmp_path / "b.pth"
    h2 = T.train(T.make_dummy_model(), loader, dev, 3, 3e-3, out_path=ckpt2, budget=T.Budget(0),
                 log=lambda m: None)
    assert h2["stopped"] and h2["loss"] == [] and ckpt2.exists() and T.resume_path(ckpt2).exists()


def test_mixed_dataset_with_hinglish_dirs_and_upsample(tmp_path):
    items, sources, _ = toy(tmp_path / "la")
    hg = tmp_path / "hg"
    (hg / "wav").mkdir(parents=True)
    (hg / "protocols").mkdir()
    sf.write(str(hg / "wav" / "bf__s1__p1.wav"), np.zeros(8000, dtype=np.float32) + 0.1, 16000)
    (hg / "protocols" / "train.txt").write_text("s1 bf__s1__p1 - - bonafide\n")
    src = T.attach_hinglish(sources, [], hg)
    hg_items = T.upsample(T.read_split_protocol(hg, "train"), 5)
    assert hg_items == [("bf__s1__p1", 1)] * 5
    assert T.read_split_protocol(hg, "val") == []
    ds = T.MixDataset(items + hg_items, src, max_len=4000)
    x, y, cond = ds[len(items)]  # a Hinglish item: only clean16k has its file, other conds fall back
    assert y == 1 and cond == "clean16k" and x.shape[0] == 4000
    assert len(T.keep_present(items + [("missing", 0)], src)) == len(items)


def test_fly_degradation_keeps_length(tmp_path):
    items = T.write_toy_corpus(tmp_path, ["raw"], 4)
    ds = T.MixDataset(items, {"g711u": [tmp_path / "raw"]}, fly=["g711u"], max_len=4000)
    x, _, cond = ds[0]
    assert cond == "g711u" and x.shape[0] == 4000


def test_lock_blocks_second_holder_and_clears_stale(tmp_path):
    lock = tmp_path / ".gpu_lock"
    with G.gpu_lock(lock):
        assert G.read_owner(lock) == os.getpid()
        with pytest.raises(G.LockHeld):
            G.acquire(lock)
    assert not lock.exists()
    lock.write_text("999999999")  # no such pid: stale
    G.acquire(lock)
    assert G.read_owner(lock) == os.getpid()
    G.release(lock)
    assert not lock.exists()


def test_main_exits_3_when_lock_held(tmp_path, monkeypatch):
    lock = tmp_path / ".gpu_lock"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    with G.gpu_lock(lock):
        rc = T.main(["--protocol", "x", "--cond-dir", f"a={tmp_path}", "--lock-file", str(lock)])
    assert rc == 3
