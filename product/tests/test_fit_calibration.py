import csv
import json

import numpy as np
import pytest

from eval import fit_calibration as fc
from service.config import load_config


def _write(path, ids, labels, bf, sl=None, with_spoof_logit=True):
    sl = np.zeros(len(ids)) if sl is None else sl
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utt_id", "label", "score"] + (["spoof_logit"] if with_spoof_logit else []))
        for u, y, s, t in zip(ids, labels, bf, sl):
            w.writerow([u, "spoof" if y else "bonafide", f"{s:.6f}"] + ([f"{t:.6f}"] if with_spoof_logit else []))


def _synth(tmp_path, n=4000, conds=("c1", "c2"), seed=1):
    rng = np.random.default_rng(seed)
    ids = [f"U{i:05d}" for i in range(n)]
    y = (np.arange(n) % 2).astype(int)  # labels fixed per utterance across conditions
    for c in conds:
        # spoof score x ~ P(x | y) so that the true calibration is logistic in x with slope ~a
        x = np.clip(fc.sigmoid(rng.normal(np.where(y == 1, 1.5, -1.5), 1.2)), 0.001, 0.999)
        sl = rng.normal(0, 1, n)  # nonzero spoof logit: x must come from the margin, not bf alone
        bf = sl - np.log(x / (1 - x))  # so that sigmoid(sl - bf) == x
        _write(tmp_path / f"{c}.csv", ids, y, bf, sl)
    return ids


def _labels_consistent(tmp_path, n=600):
    # same utterances and labels in every condition, different scores
    rng = np.random.default_rng(3)
    ids = [f"U{i:04d}" for i in range(n)]
    y = (np.arange(n) % 2).astype(int)
    for c in ("c1", "c2", "c3"):
        bf = np.where(y == 1, rng.normal(-3, 2, n), rng.normal(3, 2, n))
        _write(tmp_path / f"{c}.csv", ids, y, bf)


def test_platt_recovers_known_params():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 20000)
    y = (rng.uniform(size=x.size) < fc.sigmoid(7.0 * x - 3.5)).astype(int)
    a, b = fc.fit_platt_np(x, y)
    assert abs(a - 7.0) < 0.6 and abs(b + 3.5) < 0.4


def test_split_deterministic_no_overlap_stratified(tmp_path):
    _labels_consistent(tmp_path)
    data = fc.load_results(tmp_path)
    f1, h1 = fc.split_ids(data, seed=5)
    f2, h2 = fc.split_ids(data, seed=5)
    f3, _ = fc.split_ids(data, seed=6)
    assert f1 == f2 and h1 == h2 and f1 != f3
    assert not (f1 & h1) and len(f1) + len(h1) == 600
    labels = dict(zip(data["c1"]["ids"], data["c1"]["label"]))
    assert sum(labels[u] for u in f1) == 150 and len(f1) == 300
    # pooled rows: every condition uses the same utterances in the same split
    for c in data:
        assert {u for u in data[c]["ids"] if u in f1} == f1


def test_thresholds_respect_genuine_target(tmp_path):
    _synth(tmp_path)
    data = fc.load_results(tmp_path)
    fit, _ = fc.split_ids(data, 0)
    x, y = fc.pool(data, fit)
    a, b = fc.fit_platt_np(x, y)
    p = fc.sigmoid(a * x + b)
    weak, strong = fc.choose_thresholds(p[y == 0], 5.0, 10.0)
    assert 0 < weak < strong < 1
    assert (p[y == 0] >= strong).mean() <= 0.05 + 1e-12
    assert (p[y == 0] >= weak).mean() <= 0.10 + 1e-12
    assert (p[y == 0] >= strong).mean() > 0.03  # close to target, not wildly conservative


def test_output_config_loads_and_validates(tmp_path):
    from fastapi.testclient import TestClient
    from service.api import create_app

    res = tmp_path / "res"
    res.mkdir()
    _synth(res)
    out = tmp_path / "config.calibrated.json"
    rep = tmp_path / "CAL.md"
    base = fc.ROOT / "service" / "config.json"
    before = base.read_bytes()
    assert fc.main(["--results", str(res), "--out", str(out), "--report", str(rep)]) == 0
    assert base.read_bytes() == before
    cfg = load_config(out)
    l2 = cfg.layers["l2"]
    assert l2.weak < l2.strong and cfg.version.startswith("fitted-aasist-")
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["layers"]["l2"]["placeholder"] is False
    assert raw["layers"]["l1"]["placeholder"] is True and raw["layers"]["l4"]["placeholder"] is True
    prov = raw["provenance"]
    assert prov["split_seed"] == 0 and prov["source_csvs"] == ["c1.csv", "c2.csv"]
    assert prov["n_utterances_fit"] + prov["n_utterances_heldout"] == 4000
    assert "HELD-OUT" in rep.read_text(encoding="utf-8")
    with TestClient(create_app(config_path=str(out), evidence_path=str(tmp_path / "ev.jsonl"))):
        pass


def test_mapping_equals_service_spoof_probability():
    from service.scorers import spoof_probability

    pairs = [(0.0, 0.0), (3.2, -1.1), (-2.5, 4.0), (10.0, -10.0), (-30.0, 25.0), (0.7, 0.69)]
    got = fc.service_input([p[0] for p in pairs], [p[1] for p in pairs])
    assert np.allclose(got, [spoof_probability([sp, bf]) for sp, bf in pairs], atol=1e-12)
    assert np.allclose(got, fc.sigmoid([sp - bf for sp, bf in pairs]), atol=1e-9)


def test_load_results_uses_spoof_logit(tmp_path):
    _write(tmp_path / "c1.csv", ["a", "b"], [1, 0], [-1.0, 2.0], [3.0, -0.5])
    d = fc.load_results(tmp_path)["c1"]
    assert np.allclose(d["x"], fc.sigmoid([4.0, -2.5]))


def test_csv_without_spoof_logit_raises(tmp_path):
    _write(tmp_path / "c1.csv", ["a", "b"], [1, 0], [-1.0, 2.0], with_spoof_logit=False)
    with pytest.raises(ValueError, match="spoof_logit"):
        fc.load_results(tmp_path)


def test_per_condition_thresholds_in_config_and_report(tmp_path):
    _synth(tmp_path, n=2000)
    out, rep = tmp_path / "cfg.json", tmp_path / "rep.md"
    fc.run(tmp_path, out, rep, fc.ROOT / "service" / "config.json")
    raw = json.loads(out.read_text(encoding="utf-8"))
    pc = raw["provenance"]["per_condition_thresholds"]["thresholds"]
    assert set(pc) == {"c1", "c2"} and all(v["weak"] < v["strong"] for v in pc.values())
    assert "spoof_probability" in raw["provenance"]["score_mapping"]
    assert "per-condition thresholds" in rep.read_text(encoding="utf-8")
