"""Fine-tune AASIST on telephone-degraded ASVspoof LA train audio, optionally mixed with Hinglish speech.

STATUS: `--dry-run` (tiny random data, dummy model, CPU) and the unit tests
exercise the loop, checkpointing, resume, budget and lock. The real-model path
has NOT been run against ASVspoof data yet: expect to adjust hyperparameters.

Data
----
* LA train protocol + one audio dir per condition (`--cond-dir NAME=DIR`, made
  with degrade.telephony), and/or `--fly-audio-dir DIR --fly-conds g711u,gsm`
  to degrade raw audio per sample (slow: ffmpeg per sample; use num-workers 0).
  Protocol lines whose audio is in none of the dirs are dropped (the count is
  printed), so a full protocol plus a degraded subset just trains on the subset.
* `--hinglish-dir data/hinglish`: bona fide (and optional spoof) clips of the
  TRAIN speakers from protocols/train.txt, repeated `--hinglish-weight` times.
  Their degraded copies are looked up in data/hinglish/deg/<cond>/ (clean:
  data/hinglish/wav). Spoofs for the mix come from the LA train protocol.
* Validation EER = LA dev subset (`--val-protocol/--val-dir`) pooled with the
  Hinglish val speakers (protocols/val.txt). It picks the best epoch only.

Safety: one GPU job at a time (data/.gpu_lock, see eval/gpu_lock.py); batch 8
default; `--max-minutes` stops cleanly and saves; `--resume` continues from
<out-weights>.resume.pt (a time-out mid-epoch repeats that epoch on resume).

Real run
--------
    python -m eval.train_degraded --protocol data/raw/LA/ASVspoof2019_LA_cm_protocols/ASVspoof2019.LA.cm.train.trn.txt \\
        --cond-dir clean16k=data/deg_train/clean16k --cond-dir g711u=data/deg_train/g711u \\
        --hinglish-dir data/hinglish --hinglish-weight 5 \\
        --val-protocol <dev.trl.txt> --val-dir data/deg_dev/g711u \\
        --epochs 3 --out-weights checkpoints/aasist_ftB.pth --max-minutes 45

Recipe follows clovaai/aasist: weighted cross-entropy [0.1 spoof, 0.9 bona
fide], Adam, cosine schedule, 64600-sample inputs; lr 1e-5 because this is
fine-tuning. SWA and warm-up are left out.

    python -m eval.train_degraded --dry-run
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eer import compute_eer  # noqa: E402
from eval.gpu_lock import LockHeld, gpu_lock  # noqa: E402
from eval.run_aasist import NB_SAMP, find_audio, pad_or_tile, read_protocol, subset  # noqa: E402

CLASS_WEIGHTS = (0.1, 0.9)  # [spoof, bonafide], as in the AASIST repo's main.py
DEFAULT_INIT = ROOT / "aasist" / "models" / "weights" / "AASIST.pth"


def _torch():
    import torch
    return torch


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    _torch().manual_seed(seed)


# ------------------------------------------------------------------ data
class MixDataset:
    """Each access draws a condition at random and loads that condition's copy of the utterance.

    `sources` maps condition -> list of dirs searched in order. Conditions in
    `fly` hold RAW audio and are degraded on the fly. Random crop when longer
    than `max_len`, repeat-padding when shorter. (Duck-typed map-style dataset,
    so importing this module does not need torch.)
    """

    def __init__(self, items, sources: dict, weights: Optional[dict] = None, fly=(),
                 max_len: int = NB_SAMP):
        self.items, self.max_len, self.fly = items, max_len, set(fly)
        self.sources = {c: [Path(d) for d in (ds if isinstance(ds, (list, tuple)) else [ds])]
                        for c, ds in sources.items()}
        self.conds = list(self.sources)
        w = weights or {}
        self.weights = [float(w.get(c, 1.0)) for c in self.conds]
        self.draws = {c: 0 for c in self.conds}  # per-process counter, for inspection only

    def __len__(self):
        return len(self.items)

    def _find(self, cond: str, utt: str) -> Optional[Path]:
        for d in self.sources[cond]:
            p = find_audio(d, utt)
            if p is not None:
                return p
        return None

    def _load(self, cond: str, utt: str) -> Optional[np.ndarray]:
        import soundfile as sf
        path = self._find(cond, utt)
        if path is None:
            return None
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        if cond in self.fly:
            from degrade.telephony import degrade_array
            return degrade_array(x, sr, cond, seed_key=utt)
        if sr != 16000:
            raise ValueError(f"{path} is {sr} Hz, expected 16 kHz")
        return x

    def _crop(self, x: np.ndarray) -> np.ndarray:
        if len(x) > self.max_len:
            s = random.randint(0, len(x) - self.max_len)
            return x[s:s + self.max_len]
        return pad_or_tile(x, self.max_len)

    def __getitem__(self, idx):
        torch = _torch()
        utt, label = self.items[idx]
        # global `random` is reseeded per worker/epoch by DataLoader; main() seeds it
        first = random.choices(self.conds, weights=self.weights, k=1)[0]
        for cond in [first] + [c for c in self.conds if c != first]:  # fall back to any condition with the file
            x = self._load(cond, utt)
            if x is not None:
                self.draws[cond] += 1
                return torch.from_numpy(np.ascontiguousarray(self._crop(x))), label, cond
        raise FileNotFoundError(f"{utt} not found in any condition dir")


def collate(batch):
    torch = _torch()
    xs, ys, cs = zip(*batch)
    return torch.stack(xs), torch.tensor(ys, dtype=torch.long), list(cs)


def keep_present(items: list, sources: dict) -> list:
    """Drop items whose audio is in none of the source dirs; print how many."""
    dirs = [Path(d) for ds in sources.values() for d in (ds if isinstance(ds, list) else [ds])]
    kept = [it for it in items if any(find_audio(d, it[0]) for d in dirs)]
    if len(kept) < len(items):
        print(f"note: {len(items) - len(kept)} of {len(items)} protocol items have no audio in the given dirs; skipped")
    return kept


def upsample(items: list, factor: float) -> list:
    return list(items) * max(1, int(round(factor)))


def parse_pairs(specs, ap, what: str) -> dict:
    out = {}
    for spec in specs:
        name, _, v = spec.partition("=")
        if not v:
            ap.error(f"{what} expects NAME=VALUE, got '{spec}'")
        out[name] = v
    return out


def attach_hinglish(sources: dict, fly, hinglish: Path) -> dict:
    """Add Hinglish lookup dirs to every condition (degraded copy if it exists, clean wav otherwise)."""
    out = {}
    for c, dirs in sources.items():
        deg = hinglish / "deg" / c
        extra = [hinglish / "wav"] if (c in fly or c == "clean16k") else ([deg] if deg.is_dir() else [])
        out[c] = (list(dirs) if isinstance(dirs, (list, tuple)) else [dirs]) + extra
    return out


def read_split_protocol(hinglish: Path, name: str) -> list:
    p = hinglish / "protocols" / f"{name}.txt"
    return read_protocol(p) if p.exists() else []


def make_loader(ds, batch_size: int, shuffle: bool, num_workers: int, seed: int = 0, drop_last: bool = False):
    torch = _torch()
    gen = torch.Generator().manual_seed(seed)
    return torch.utils.data.DataLoader(ds, batch_size=batch_size, shuffle=shuffle, collate_fn=collate,
                                       num_workers=num_workers, drop_last=drop_last, generator=gen)


# ---------------------------------------------------------- train / eval
class Budget:
    """Wall-clock budget; `None` minutes = unlimited."""

    def __init__(self, minutes: Optional[float]):
        self.end = None if minutes is None else time.monotonic() + 60 * minutes

    def expired(self) -> bool:
        return self.end is not None and time.monotonic() >= self.end


def evaluate_eer(model, loader, device) -> float:
    torch = _torch()
    model.eval()
    bona, spoof = [], []
    with torch.no_grad():
        for x, y, _ in loader:
            _, out = model(x.to(device))
            s = out[:, 1].cpu().numpy()
            for sc, lab in zip(s, y.numpy()):
                (bona if lab == 1 else spoof).append(float(sc))
    if not bona or not spoof:
        return float("nan")
    return compute_eer(bona, spoof)[0]


def train_one_epoch(model, loader, device, opt, sched, criterion, scaler, grad_clip: float,
                    budget: Budget, amp: bool) -> tuple:
    """-> (mean loss, finished). finished=False when the wall-clock budget ran out mid-epoch."""
    torch = _torch()
    model.train()
    run, n = 0.0, 0
    for x, y, _ in loader:
        if budget.expired():
            return run / max(n, 1), False
        x, y = x.to(device), y.to(device)
        with torch.autocast(device_type=device.type, enabled=amp):
            _, out = model(x)
            loss = criterion(out.float(), y)
        opt.zero_grad()
        scaler.scale(loss).backward()
        if grad_clip > 0:
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        scaler.step(opt)
        scaler.update()
        sched.step()
        run += loss.item() * len(y)
        n += len(y)
    return run / max(n, 1), True


# ----------------------------------------------------------- checkpoints
def resume_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.name + ".resume.pt")


def save_weights(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _torch().save(model.state_dict(), path)


def save_resume(path: Path, model, opt, sched, scaler, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _torch().save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                   "scaler": scaler.state_dict(), "state": state}, path)


def load_resume(path: Path, model, opt, sched, scaler, device) -> dict:
    ck = _torch().load(path, map_location=device, weights_only=False)
    model.load_state_dict(ck["model"])
    opt.load_state_dict(ck["opt"])
    sched.load_state_dict(ck["sched"])
    scaler.load_state_dict(ck["scaler"])
    return ck["state"]


def train(model, train_loader, device, epochs: int, lr: float, weight_decay: float = 1e-4,
          val_loader=None, out_path: Optional[Path] = None, log=print, grad_clip: float = 5.0,
          amp: bool = False, budget: Optional[Budget] = None, resume: bool = False) -> dict:
    """Weighted CE, Adam, cosine schedule over all steps; best-by-val-EER checkpoint at out_path
    (last epoch when there is no val set); resumable state next to it. Returns a history dict."""
    torch = _torch()
    budget = budget or Budget(None)
    criterion = torch.nn.CrossEntropyLoss(weight=torch.tensor(CLASS_WEIGHTS, dtype=torch.float32, device=device))
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    total_steps = max(1, epochs * len(train_loader))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda step: 0.5 * (1 + math.cos(math.pi * min(step, total_steps) / total_steps)))
    scaler = torch.amp.GradScaler("cuda", enabled=amp and device.type == "cuda")

    state = {"epoch": 0, "best": float("inf"), "hist": {"loss": [], "val_eer": []}, "stopped": None}
    rpath = resume_path(out_path) if out_path else None
    if resume and rpath is not None and rpath.exists():
        state = load_resume(rpath, model, opt, sched, scaler, device)
        state["stopped"] = None
        log(f"resumed from {rpath} at epoch {state['epoch']}")
    hist = state["hist"]

    for ep in range(state["epoch"], epochs):
        loss, finished = train_one_epoch(model, train_loader, device, opt, sched, criterion, scaler,
                                         grad_clip, budget, amp)
        if not finished:
            state["stopped"] = "max-minutes budget"
            log(f"budget reached during epoch {ep + 1}; saving and stopping")
            break
        hist["loss"].append(loss)
        msg = f"epoch {ep + 1}/{epochs} loss {loss:.4f}"
        if val_loader is not None:
            eer = evaluate_eer(model, val_loader, device)
            hist["val_eer"].append(eer)
            msg += f" val_eer {eer * 100:.2f}%"
            if out_path is not None and not math.isnan(eer) and eer < state["best"]:
                state["best"] = eer
                save_weights(model, out_path)
        elif out_path is not None:
            save_weights(model, out_path)
        state["epoch"] = ep + 1
        if rpath is not None:
            save_resume(rpath, model, opt, sched, scaler, state)
        log(msg)
    if state["stopped"] and out_path is not None:
        if not out_path.exists():
            save_weights(model, out_path)  # nothing validated yet: keep the current weights rather than nothing
        save_resume(rpath, model, opt, sched, scaler, state)
    hist["stopped"] = state["stopped"]
    return hist


# --------------------------------------------------------------- dry run
def make_dummy_model():
    torch = _torch()
    nn = torch.nn

    class Dummy(nn.Module):
        """Stand-in with AASIST's interface: forward(x[B,T]) -> (hidden, logits[B,2])."""

        def __init__(self):
            super().__init__()
            self.conv = nn.Conv1d(1, 8, 64, stride=16)
            self.fc = nn.Linear(8, 2)

        def forward(self, x):
            h = torch.relu(self.conv(x.unsqueeze(1))).mean(dim=2)
            return h, self.fc(h)

    return Dummy()


def write_toy_corpus(tmp: Path, conds: list, n_utts: int, n_samp: int = 4000, sr: int = 16000) -> list:
    """Separable toy data (bonafide = tone + noise, spoof = noise); returns [(utt, label)]."""
    import soundfile as sf
    rng = np.random.default_rng(0)
    items = []
    for i in range(n_utts):
        label = i % 2  # 1 = bonafide
        t = np.arange(n_samp + (i % 5) * 300) / sr
        sig = 0.05 * rng.standard_normal(len(t))
        if label == 1:
            sig = sig + 0.4 * np.sin(2 * np.pi * 300 * t)
        items.append((f"UTT_{i:03d}", label))
        for c in conds:
            (tmp / c).mkdir(parents=True, exist_ok=True)
            s = sig * (0.9 if c != "clean16k" else 1.0)
            sf.write(str(tmp / c / f"UTT_{i:03d}.wav"), s.astype(np.float32), sr, subtype="PCM_16")
    return items


def dry_run() -> int:
    torch = _torch()
    seed_everything(0)
    conds = ["clean16k", "g711u", "gsm"]
    with tempfile.TemporaryDirectory(prefix="dryrun_") as tmp:
        tmp = Path(tmp)
        items = write_toy_corpus(tmp, conds, 48)
        sources = {c: tmp / c for c in conds}
        ds = MixDataset(items, sources, max_len=4000)
        loader = make_loader(ds, 8, True, 0)
        val = make_loader(MixDataset(items, sources, max_len=4000), 8, False, 0)
        model = make_dummy_model()
        ckpt = tmp / "ckpt.pth"
        hist = train(model, loader, torch.device("cpu"), epochs=6, lr=3e-3, val_loader=val, out_path=ckpt)

        ok = True
        if not all(math.isfinite(v) for v in hist["loss"]):
            print("FAIL: non-finite loss"); ok = False
        if not hist["loss"][-1] < hist["loss"][0]:
            print(f"FAIL: loss did not decrease ({hist['loss'][0]:.4f} -> {hist['loss'][-1]:.4f})"); ok = False
        if not ckpt.exists():
            print("FAIL: checkpoint not written"); ok = False
        if len([c for c, k in ds.draws.items() if k > 0]) < 2:
            print(f"FAIL: only conditions {ds.draws} were sampled"); ok = False
        make_dummy_model().load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=True))  # reloads cleanly
        print(f"dry-run: loss {hist['loss'][0]:.4f} -> {hist['loss'][-1]:.4f}, "
              f"val EER {hist['val_eer'][-1] * 100:.1f}%, conditions sampled {ds.draws}")
        print("dry-run OK" if ok else "dry-run FAILED")
        return 0 if ok else 1


# -------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fine-tune AASIST on degraded LA train (+ Hinglish).")
    ap.add_argument("--dry-run", action="store_true", help="tiny random data, dummy model, CPU; no repo needed")
    ap.add_argument("--aasist-repo", type=Path, default=ROOT / "aasist")
    ap.add_argument("--model", choices=["AASIST", "AASIST-L"], default="AASIST")
    ap.add_argument("--init-weights", "--weights", dest="init_weights", type=Path, default=DEFAULT_INIT,
                    help="starting weights, absolute path (default: aasist/models/weights/AASIST.pth)")
    ap.add_argument("--protocol", type=Path, help="LA train protocol (ASVspoof2019.LA.cm.train.trn.txt)")
    ap.add_argument("--cond-dir", action="append", default=[], metavar="NAME=DIR",
                    help="precomputed degraded copy of the train audio for one condition (repeatable)")
    ap.add_argument("--fly-audio-dir", type=Path, help="raw LA train audio, degraded per sample by --fly-conds")
    ap.add_argument("--fly-conds", default="", help="comma-separated degrade.telephony conditions for --fly-audio-dir")
    ap.add_argument("--cond-weights", default="", help="e.g. clean16k=2,gsm=1 (default: all 1)")
    ap.add_argument("--hinglish-dir", type=Path, help="data/hinglish: adds train-split speakers from protocols/train.txt")
    ap.add_argument("--hinglish-weight", type=float, default=5.0, help="repeat Hinglish train clips this many times")
    ap.add_argument("--val-protocol", type=Path)
    ap.add_argument("--val-dir", type=Path, help="one (degraded) dir with the val-protocol audio")
    ap.add_argument("--val-limit", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--num-workers", type=int, default=0, help="keep 0 on Windows")
    ap.add_argument("--grad-clip", type=float, default=5.0, help="max grad norm, 0 = off")
    ap.add_argument("--amp", action="store_true", help="mixed precision (cuda only)")
    ap.add_argument("--max-minutes", type=float, default=None, help="wall-clock budget; stops cleanly and saves")
    ap.add_argument("--resume", action="store_true", help="continue from <out-weights>.resume.pt if present")
    ap.add_argument("--limit", type=int, default=None, help="use only N LA training utterances")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--out-weights", "--out", dest="out_weights", type=Path,
                    default=Path("checkpoints/aasist_mix.pth"))
    ap.add_argument("--lock-file", type=Path, default=None, help="default data/.gpu_lock")
    return ap


def build_train_loader(a, ap):
    sources = {n: [Path(d)] for n, d in parse_pairs(a.cond_dir, ap, "--cond-dir").items()}
    fly = [c for c in a.fly_conds.split(",") if c]
    if fly:
        if not a.fly_audio_dir:
            ap.error("--fly-conds needs --fly-audio-dir")
        sources.update({c: [a.fly_audio_dir] for c in fly})
    if a.hinglish_dir:
        sources = attach_hinglish(sources, fly, a.hinglish_dir)
    la = keep_present(subset(read_protocol(a.protocol), a.limit, a.seed), sources)
    hg = upsample(read_split_protocol(a.hinglish_dir, "train"), a.hinglish_weight) if a.hinglish_dir else []
    if a.hinglish_dir and not hg:
        print("note: no Hinglish train split (test-only data); training on LA only")
    print(f"train items: {len(la)} LA + {len(hg)} Hinglish (weight {a.hinglish_weight:g})")
    weights = {k: float(v) for k, v in parse_pairs(filter(None, a.cond_weights.split(",")), ap, "--cond-weights").items()}
    ds = MixDataset(la + hg, sources, weights, fly=fly)
    return make_loader(ds, a.batch_size, True, a.num_workers, a.seed, drop_last=True)


def build_val_loader(a):
    items, dirs = [], []
    if a.val_protocol and a.val_dir:
        items += subset(read_protocol(a.val_protocol), a.val_limit, a.seed, balanced=True)
        dirs.append(a.val_dir)
    if a.hinglish_dir:
        hv = read_split_protocol(a.hinglish_dir, "val")
        items += hv
        dirs += [a.hinglish_dir / "wav"] if hv else []
    if not items:
        return None
    print(f"val items: {len(items)}")
    return make_loader(MixDataset(items, {"val": dirs}), a.batch_size, False, a.num_workers)


def run_training(a, ap) -> int:
    from eval.run_aasist import load_model
    torch = _torch()
    device = torch.device(a.device)
    seed_everything(a.seed)
    train_loader = build_train_loader(a, ap)
    val_loader = build_val_loader(a)
    model = load_model(a.aasist_repo, a.model, device, a.init_weights.resolve())
    hist = train(model, train_loader, device, a.epochs, a.lr, val_loader=val_loader, out_path=a.out_weights,
                 grad_clip=a.grad_clip, amp=a.amp, budget=Budget(a.max_minutes), resume=a.resume)
    print(f"saved to {a.out_weights}" + (f" (stopped: {hist['stopped']}; rerun with --resume)" if hist["stopped"] else ""))
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.dry_run:
        return dry_run()
    if not (a.protocol and (a.cond_dir or a.fly_conds)):
        ap.error("--protocol and --cond-dir (or --fly-conds) are required (or use --dry-run)")
    if a.amp and a.device != "cuda":
        ap.error("--amp needs --device cuda")
    torch = _torch()
    if a.device == "cuda" and not torch.cuda.is_available():
        print("error: CUDA not available; use --device cpu", file=sys.stderr)
        return 2
    try:
        if a.device == "cpu":
            return run_training(a, ap)
        with gpu_lock(*([a.lock_file] if a.lock_file else [])):
            return run_training(a, ap)
    except LockHeld as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
