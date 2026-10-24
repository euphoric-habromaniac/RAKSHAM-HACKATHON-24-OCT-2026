import json

import pytest

from eval.run_aasist import read_protocol
from tools import make_hinglish_protocol as MP
from tools import split_hinglish as S
from tools.hinglish_data import write_manifest

ACCENTS = ["Hindi", "Punjabi", "Marathi", "Bengali"]


def rows_for(n, spoof_for=()):
    rows = []
    for i in range(n):
        spk, acc = f"s{i:02d}", ACCENTS[i % 4]
        for lab, tag in [("bonafide", "bf")] + ([("spoof", "sp")] if spk in spoof_for else []):
            for p in range(2):
                rows.append({"utt_id": f"{tag}__{spk}__p{p}", "speaker_id": spk, "phrase_id": f"p{p}",
                             "label": lab, "language": "hinglish", "accent_group": acc, "age_band": "x",
                             "gender": "f", "device": "d", "duration_s": "2.0", "sha1": f"{spk}{lab}{p}",
                             "file": "wav/x.wav"})
    return rows


@pytest.mark.parametrize("n,sizes", [(2, (0, 0, 2)), (5, (0, 0, 5)), (8, (3, 1, 4)), (9, (4, 1, 4)),
                                     (10, (6, 1, 3)), (14, (8, 1, 5))])
def test_split_sizes_and_disjoint(n, sizes):
    sp = S.build_splits(rows_for(n), seed=0)
    S.check_disjoint(sp)
    counts = tuple(sum(v == k for v in sp["speakers"].values()) for k in ("train", "val", "heldout"))
    assert counts == sizes and len(sp["speakers"]) == n


def test_deterministic_and_seed_changes_assignment():
    a = S.build_splits(rows_for(12), seed=0)
    assert a == S.build_splits(rows_for(12), seed=0)
    assert any(S.build_splits(rows_for(12), seed=k)["speakers"] != a["speakers"] for k in range(1, 6))


def test_heldout_spans_accent_groups():
    sp = S.build_splits(rows_for(10), seed=3)
    held = {sp["accent"][s] for s, v in sp["speakers"].items() if v == "heldout"}
    assert len(held) >= 3


def test_claim_levels():
    assert S.build_splits(rows_for(3), 0)["claim_level"].startswith("S1")
    assert S.build_splits(rows_for(6), 0)["claim_level"].startswith("S3")
    assert S.build_splits(rows_for(10), 0)["claim_level"].startswith("S4")
    one_accent = rows_for(10)
    for r in one_accent:
        r["accent_group"] = "Hindi"
    assert S.build_splits(one_accent, 0)["claim_level"].startswith("S3")


def test_cli_freezes_splits(tmp_path):
    write_manifest(tmp_path / "manifest.csv", rows_for(10))
    assert S.main(["--hinglish", str(tmp_path)]) == 0
    first = json.loads((tmp_path / "splits.json").read_text())["speakers"]
    write_manifest(tmp_path / "manifest.csv", rows_for(11))
    assert S.main(["--hinglish", str(tmp_path)]) == 2  # speaker set changed: refuses
    assert json.loads((tmp_path / "splits.json").read_text())["speakers"] == first
    assert S.main(["--hinglish", str(tmp_path), "--force"]) == 0


def test_protocol_roundtrip_through_run_aasist_parser(tmp_path):
    rows = rows_for(10, spoof_for=tuple(f"s{i:02d}" for i in range(10)))
    write_manifest(tmp_path / "manifest.csv", rows)
    S.main(["--hinglish", str(tmp_path)])
    counts = MP.write_protocols(tmp_path)
    splits = json.loads((tmp_path / "splits.json").read_text())
    seen = set()
    for name, n in counts.items():
        items = read_protocol(tmp_path / "protocols" / f"{name}.txt")
        assert len(items) == n
        for utt, lab in items:
            assert splits["speakers"][utt.split("__")[1]] == name
            assert lab == (1 if utt.startswith("bf__") else 0)
        seen |= {u for u, _ in items}
    assert seen == {r["utt_id"] for r in rows}
    first = (tmp_path / "protocols" / "heldout.txt").read_text().splitlines()[0].split()
    assert first[2] == "-" and first[4] in ("bonafide", "spoof")  # LA column layout
