"""Hash-chained evidence log."""
import json

import pytest

from service.evidence import GENESIS_HASH, EvidenceError, EvidenceLog, compute_hash, verify_chain


def make_log(tmp_path, n=4):
    log = EvidenceLog(tmp_path / "ev.jsonl")
    for i in range(n):
        log.append(f"call-{i % 2}", "band_decided", {"band": "Clear", "i": i}, 1_800_000_000.0 + i)
    return log


def lines(path):
    return path.read_text().splitlines()


def test_empty_or_missing_log_verifies(tmp_path):
    r = verify_chain(tmp_path / "nope.jsonl")
    assert r.ok and r.records == 0 and r.head_hash == GENESIS_HASH


def test_chain_links_and_verifies(tmp_path):
    log = make_log(tmp_path)
    recs = log.records()
    assert recs[0]["prev_hash"] == GENESIS_HASH
    for a, b in zip(recs, recs[1:]):
        assert b["prev_hash"] == a["hash"]
    assert all(r["hash"] == compute_hash(r) for r in recs)
    res = log.verify()
    assert res.ok and res.records == 4 and res.head_hash == log.head_hash()


def test_records_carry_timestamp_call_and_event(tmp_path):
    rec = make_log(tmp_path, 1).records()[0]
    assert rec["ts"].endswith("+00:00") and "T" in rec["ts"]
    assert rec["call_id"] == "call-0" and rec["event"] == "band_decided"


def test_filter_by_call(tmp_path):
    assert len(make_log(tmp_path).records("call-1")) == 2


def test_tampered_content_detected(tmp_path):
    log = make_log(tmp_path)
    ls = lines(log.path)
    rec = json.loads(ls[1])
    rec["data"]["band"] = "Hold"
    ls[1] = json.dumps(rec, sort_keys=True)
    log.path.write_text("\n".join(ls) + "\n")
    res = verify_chain(log.path)
    assert not res.ok and res.bad_seq == 1 and "hash mismatch" in res.reason


def test_tampered_content_with_recomputed_hash_breaks_next_link(tmp_path):
    log = make_log(tmp_path)
    ls = lines(log.path)
    rec = json.loads(ls[1])
    rec["data"]["band"] = "Hold"
    rec["hash"] = compute_hash(rec)
    ls[1] = json.dumps(rec, sort_keys=True)
    log.path.write_text("\n".join(ls) + "\n")
    res = verify_chain(log.path)
    assert not res.ok and res.bad_seq == 2 and "prev_hash" in res.reason


def test_deleted_middle_record_detected(tmp_path):
    log = make_log(tmp_path)
    ls = lines(log.path)
    del ls[1]
    log.path.write_text("\n".join(ls) + "\n")
    assert not verify_chain(log.path).ok


def test_reordered_records_detected(tmp_path):
    log = make_log(tmp_path)
    ls = lines(log.path)
    ls[1], ls[2] = ls[2], ls[1]
    log.path.write_text("\n".join(ls) + "\n")
    assert not verify_chain(log.path).ok


def test_garbage_line_detected(tmp_path):
    log = make_log(tmp_path)
    with log.path.open("a") as fh:
        fh.write("not json\n")
    res = verify_chain(log.path)
    assert not res.ok and res.reason == "unparseable record"


def test_reopening_continues_the_chain(tmp_path):
    log = make_log(tmp_path, 2)
    again = EvidenceLog(log.path)
    again.append("c", "x", {}, 1_800_000_100.0)
    assert verify_chain(log.path).ok and verify_chain(log.path).records == 3


def test_reopening_corrupt_log_raises(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("garbage\n")
    with pytest.raises(EvidenceError):
        EvidenceLog(p)


def test_append_is_append_only_on_disk(tmp_path):
    log = make_log(tmp_path, 2)
    before = lines(log.path)
    log.append("c", "x", {}, 1_800_000_100.0)
    assert lines(log.path)[:2] == before
