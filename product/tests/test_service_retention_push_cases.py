import pytest
import time
import os
from pathlib import Path
from service.push import generate_prompt_token, verify_prompt_token
from service.cases import CaseStore, FraudCase
from service.retention import RetentionManager, get_retention_ttl_seconds


def test_push_prompt_token_generation_and_verification():
    token = generate_prompt_token(
        call_id="call_99",
        customer_id="cust_42",
        request_type="wire_transfer",
        amount=50000.0,
        payee="Evil Corp",
        ttl_seconds=10.0,
    )
    assert "." in token
    payload = verify_prompt_token(token)
    assert payload["call_id"] == "call_99"
    assert payload["customer_id"] == "cust_42"
    assert payload["amount"] == 50000.0


def test_push_prompt_token_tampering_rejected():
    token = generate_prompt_token("c1", "u1", "limit_change", ttl_seconds=10.0)
    parts = token.split(".")
    tampered = parts[0] + "tamper." + parts[1]
    with pytest.raises(ValueError, match="signature verification failed|Malformed"):
        verify_prompt_token(tampered)


def test_push_prompt_token_expiration():
    token = generate_prompt_token("c1", "u1", "limit_change", ttl_seconds=5.0)
    future_time = time.time() + 10.0
    with pytest.raises(ValueError, match="expired"):
        verify_prompt_token(token, current_time=future_time)


def test_case_lifecycle(tmp_path):
    store = CaseStore(base_dir=tmp_path)
    case = store.create_case("call_1", "hmac_cust_1", {"reasons": ["l2_strong"]})
    assert case.status == "HELD"
    assert case.call_id == "call_1"

    # Assign
    assigned = store.assign(case.case_id, "analyst_alice")
    assert assigned.status == "ANALYSIS"
    assert assigned.assigned_to == "analyst_alice"

    # Add Note
    noted = store.add_note(case.case_id, "analyst_alice", "Customer confirmed in person.")
    assert len(noted.notes) == 1
    assert noted.notes[0].text == "Customer confirmed in person."

    # Resolve
    resolved = store.resolve(case.case_id, "DISMISS", "Customer verified via secondary branch contact.")
    assert resolved.status == "RESOLVED"
    assert resolved.resolution == "DISMISS"


def test_retention_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RETENTION_PERIOD_SECONDS", "30")
    assert get_retention_ttl_seconds() == 30.0

    mgr = RetentionManager(data_dir=tmp_path)
    old_file = mgr.audio_dir / "old_call.enc"
    old_file.write_bytes(b"encrypted_audio")

    # Set file mtime to 100 seconds ago
    past = time.time() - 100
    os.utime(old_file, (past, past))

    res = mgr.purge_expired()
    assert res["deleted_audio_count"] == 1
    assert not old_file.exists()


def test_no_clear_audio_on_disk(tmp_path):
    mgr = RetentionManager(data_dir=tmp_path)
    # Clear calls must never leave audio clips on disk
    clear_ids = ["call_clear_1", "call_clear_2"]
    assert mgr.verify_no_clear_audio_on_disk(clear_ids) is True

    # If an audio clip for clear call is created, test fails
    leak = mgr.audio_dir / "call_clear_1_chunk.wav"
    leak.write_bytes(b"leaked")
    assert mgr.verify_no_clear_audio_on_disk(clear_ids) is False
