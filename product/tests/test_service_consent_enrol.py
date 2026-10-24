import pytest
import numpy as np
from service.consent import ConsentRecord, save_consent, get_consent, verify_consent_for_cloning, assert_consent_for_cloning
from service.enrol import EnrolmentStore, VoiceprintRecord


def test_consent_gate_refusal_when_missing(tmp_path):
    assert verify_consent_for_cloning("unknown_speaker", consent_dir=tmp_path) is False
    with pytest.raises(PermissionError, match="Consent gate violation"):
        assert_consent_for_cloning("unknown_speaker", consent_dir=tmp_path)


def test_consent_gate_refusal_when_unsigned(tmp_path):
    record = ConsentRecord(speaker_id="spk1", full_name="User One", signed=False, allow_voice_cloning=True)
    save_consent(record, consent_dir=tmp_path)
    assert verify_consent_for_cloning("spk1", consent_dir=tmp_path) is False
    with pytest.raises(PermissionError):
        assert_consent_for_cloning("spk1", consent_dir=tmp_path)


def test_consent_gate_refusal_when_cloning_not_allowed(tmp_path):
    record = ConsentRecord(speaker_id="spk2", full_name="User Two", signed=True, allow_voice_cloning=False)
    save_consent(record, consent_dir=tmp_path)
    assert verify_consent_for_cloning("spk2", consent_dir=tmp_path) is False
    with pytest.raises(PermissionError):
        assert_consent_for_cloning("spk2", consent_dir=tmp_path)


def test_consent_gate_passes_when_signed_with_cloning(tmp_path):
    record = ConsentRecord(speaker_id="spk3", full_name="User Three", signed=True, allow_voice_cloning=True)
    save_consent(record, consent_dir=tmp_path)
    assert verify_consent_for_cloning("spk3", consent_dir=tmp_path) is True
    assert_consent_for_cloning("spk3", consent_dir=tmp_path)


def test_enrolment_and_withdrawal(tmp_path):
    store = EnrolmentStore(base_dir=tmp_path)
    emb = np.random.randn(192).astype(np.float32)
    # Without consent enforced
    rec = store.enrol("cust_1", emb, enforce_consent=False)
    assert rec.customer_id == "cust_1"
    assert rec.embedding_dim == 192

    loaded = store.get_embedding("cust_1")
    assert loaded is not None
    assert np.allclose(loaded, emb, atol=1e-5)

    # Withdraw
    assert store.withdraw("cust_1") is True
    assert store.get_embedding("cust_1") is None
