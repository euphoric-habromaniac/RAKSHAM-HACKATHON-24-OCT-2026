"""End-to-end API behaviour with mock scorers, a manual clock, and a temp evidence log."""
import json
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from service import audio
from service.api import create_app
from service.evidence import verify_chain
from service.testing import FakeClock, tone_b64

AGENT = {"X-User": "agent-1", "X-Role": "agent"}
ANALYST = {"X-User": "analyst-1", "X-Role": "analyst"}
HEAD1 = {"X-User": "head-1", "X-Role": "fraud_head"}
HEAD2 = {"X-User": "head-2", "X-Role": "fraud_head"}
DIGITS = re.compile(r"(\d(?: \d){5})")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ev_path(tmp_path):
    return tmp_path / "evidence.jsonl"


@pytest.fixture
def client(clock, ev_path):
    with TestClient(create_app(evidence_path=str(ev_path), clock=clock)) as c:
        yield c


def start(client, call_id="c1", request_type="balance", enrolled=True, flags=None, **meta):
    r = client.post("/calls", json={"call_id": call_id, "customer_id": "cust", "request_type": request_type,
                                    "enrolled": enrolled, "bank_flags": flags or {}, "metadata": meta})
    assert r.status_code == 201, r.text
    return r.json()


def speak(client, call_id="c1", text="mera balance bata dijiye", sample_rate=8000):
    client.post(f"/calls/{call_id}/audio", json={"pcm_b64": tone_b64(), "sample_rate": sample_rate}).raise_for_status()
    r = client.post(f"/calls/{call_id}/transcript", json={"text": text})
    r.raise_for_status()
    return r.json()


def digits_of(view):
    return DIGITS.search(view["agent_message"]).group(1).split()


def answer(client, clock, call_id, text, after=4.0):
    clock.advance(after)
    r = client.post(f"/calls/{call_id}/challenge/answer", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ Clear
def test_genuine_caller_is_clear(client):
    start(client, mock_l1_cosine=0.82, mock_l2_spoof=0.04)
    v = speak(client)
    assert v["band"] == "Clear" and v["status"] == "clear"
    assert client.get("/calls/c1").json()["band"] == "Clear"


def test_band_is_pending_until_audio_and_transcript_both_arrive(client):
    start(client)
    r = client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    assert r.json()["band"] is None
    assert client.get("/calls/c1").json()["status"] == "collecting"


def test_one_weak_signal_never_holds(client):
    start(client, mock_l2_spoof=0.45)  # weak with placeholder calibration
    v = speak(client)
    assert v["band"] == "Clear"
    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert detail["layers"]["l2"]["strength"] == "weak"


# ---------------------------------------------------------------- Step up
def test_sensitive_request_steps_up_with_six_digits(client):
    start(client, request_type="limit_change")
    v = speak(client, text="limit badhani hai")
    assert v["band"] == "Step up" and v["challenge_pending"]
    assert v["agent_message"].startswith("Voice could not be confirmed. Ask the caller to repeat these six digits: ")
    assert len(digits_of(v)) == 6


def test_one_strong_signal_steps_up(client):
    start(client, mock_l2_spoof=0.9)
    assert speak(client)["band"] == "Step up"


def test_two_weak_signals_step_up(client):
    start(client, mock_l1_cosine=0.55, mock_l2_spoof=0.55)
    assert speak(client)["band"] == "Step up"


def test_correct_digits_in_english_pass_and_stay_step_up(client, clock):
    start(client, request_type="new_payee")
    v = speak(client)
    out = answer(client, clock, "c1", " ".join(digits_of(v)))
    assert out["band"] == "Step up" and out["status"] == "challenge_passed"
    assert not out["challenge_pending"]


def test_correct_digits_spoken_in_hindi_pass(client, clock):
    words = {"0": "shunya", "1": "ek", "2": "do", "3": "teen", "4": "char", "5": "paanch",
             "6": "chhah", "7": "saat", "8": "aath", "9": "nau"}
    start(client, request_type="device_change")
    v = speak(client)
    out = answer(client, clock, "c1", " ".join(words[d] for d in digits_of(v)))
    assert out["status"] == "challenge_passed"


def test_wrong_digits_hold_and_prompt_app(client, clock):
    start(client, request_type="limit_change")
    d = digits_of(speak(client))
    d[0] = str((int(d[0]) + 1) % 10)
    out = answer(client, clock, "c1", " ".join(d))
    assert out["band"] == "Hold" and out["app_prompt_pending"]
    assert out["agent_message"] == ("Request paused. The customer will get a prompt in the bank app. "
                                    "An analyst will review.")


def test_unclear_answer_holds(client, clock):
    start(client, request_type="limit_change")
    speak(client)
    assert answer(client, clock, "c1", "sorry what")["band"] == "Hold"


def test_slow_reply_holds(client, clock):
    start(client, request_type="limit_change")
    d = digits_of(speak(client))
    assert answer(client, clock, "c1", " ".join(d), after=30.0)["band"] == "Hold"


def test_challenge_answer_by_audio_goes_through_asr(client, clock):
    # The mock ASR returns metadata['mock_asr_text'], so it can supply the correct digits only
    # if the test knows them; here it returns '' and the answer is therefore unclear -> Hold.
    start(client, request_type="limit_change", mock_asr_text="")
    speak(client)
    clock.advance(4)
    r = client.post("/calls/c1/challenge/answer", json={"pcm_b64": tone_b64()})
    assert r.json()["band"] == "Hold"
    assert client.get("/cases/c1", headers=ANALYST).json()["challenge"]["outcome"] == "unclear"


def test_challenge_answer_needs_exactly_one_of_text_or_audio(client):
    start(client, request_type="limit_change")
    speak(client)
    assert client.post("/calls/c1/challenge/answer", json={}).status_code == 422
    both = {"text": "1 2 3 4 5 6", "pcm_b64": tone_b64()}
    assert client.post("/calls/c1/challenge/answer", json=both).status_code == 422


def test_challenge_answer_without_pending_challenge_is_409(client):
    start(client)
    speak(client)
    assert client.post("/calls/c1/challenge/answer", json={"text": "1 2 3 4 5 6"}).status_code == 409


# ------------------------------------------------------------------- Hold
def test_two_strong_signals_hold_immediately(client):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    v = speak(client, text="urgent jaldi karo")
    assert v["band"] == "Hold" and v["app_prompt_pending"] and not v["challenge_pending"]


def test_app_response_recorded_and_does_not_release(client):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    speak(client, text="urgent jaldi karo")
    for result in ("approve",):
        v = client.post("/calls/c1/app-response", json={"result": result}).json()
        assert v["band"] == "Hold" and not v["app_prompt_pending"]
    assert client.get("/cases/c1", headers=ANALYST).json()["app_confirmation"]["result"] == "approve"
    assert client.post("/calls/c1/app-response", json={"result": "deny"}).status_code == 409


@pytest.mark.parametrize("result", ["deny", "timeout"])
def test_app_deny_and_timeout_accepted(client, result):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    speak(client, text="urgent jaldi karo")
    assert client.post("/calls/c1/app-response", json={"result": result}).status_code == 200


def test_app_response_only_exists_on_hold(client):
    start(client)
    speak(client)
    assert client.post("/calls/c1/app-response", json={"result": "approve"}).status_code == 409


def test_not_enrolled_sensitive_request_goes_to_app_confirmation(client):
    start(client, request_type="new_payee", enrolled=False)
    v = speak(client)
    assert v["band"] == "Hold" and v["app_prompt_pending"]
    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert "l1" not in detail["layers"] and "l1" not in detail["models"]


def test_not_enrolled_ordinary_request_ignores_l1(client):
    start(client, enrolled=False, mock_l1_cosine=0.0)
    assert speak(client)["band"] == "Clear"


# --------------------------------------------------------------- fail open
def test_model_error_fails_open_and_is_logged(client, ev_path, caplog):
    start(client, mock_error="l2")
    with caplog.at_level("WARNING", logger="asli.failopen"):
        r = client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    v = r.json()
    assert v["band"] == "Unavailable"
    assert "normal bank process" in v["agent_message"]
    assert any("failing open" in rec.message for rec in caplog.records)
    events = [json.loads(l)["event"] for l in ev_path.read_text().splitlines()]
    assert "fail_open" in events
    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert detail["fail_open"]["reason"].startswith("model_error")


def test_l1_error_on_enrolled_call_fails_open(client):
    start(client, mock_error="l1")
    assert client.post("/calls/c1/audio", json={"pcm_b64": tone_b64()}).json()["band"] == "Unavailable"


def test_late_scoring_fails_open(client, clock):
    start(client)
    client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    clock.advance(10.5)
    v = client.post("/calls/c1/transcript", json={"text": "balance"}).json()
    assert v["band"] == "Unavailable"


def test_deadline_is_lazily_enforced_on_read(client, clock):
    start(client)
    client.post("/calls/c1/audio", json={"pcm_b64": tone_b64()})
    clock.advance(11)
    assert client.get("/calls/c1").json()["band"] == "Unavailable"


def test_deadline_runs_from_first_reply_not_call_start(client, clock):
    start(client)
    clock.advance(60)  # caller silent for a minute: clock not running yet
    client.post("/calls/c1/audio", json={"pcm_b64": tone_b64()})
    clock.advance(9.5)
    assert client.post("/calls/c1/transcript", json={"text": "balance"}).json()["band"] == "Clear"


def test_deadline_is_configurable(clock, ev_path):
    from service.config import load_config
    cfg = load_config()
    cfg.deadline_seconds = 2.0
    with TestClient(create_app(config=cfg, evidence_path=str(ev_path), clock=clock)) as c:
        start(c)
        c.post("/calls/c1/audio", json={"pcm_b64": tone_b64()})
        clock.advance(3)
        assert c.get("/calls/c1").json()["band"] == "Unavailable"


def test_asr_error_during_challenge_fails_open(client, clock):
    start(client, request_type="limit_change", mock_error="asr")
    speak(client)
    clock.advance(4)
    r = client.post("/calls/c1/challenge/answer", json={"pcm_b64": tone_b64()})
    assert r.json()["band"] == "Unavailable"


# ------------------------------------------------------ what the agent sees
def test_agent_view_never_exposes_scores_or_firing_layer(client, clock):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9, mock_l1_cosine=0.2)
    body = speak(client, text="urgent jaldi")
    assert set(body) == {"call_id", "status", "band", "agent_message", "challenge_pending", "app_prompt_pending",
                         "seq"}
    msg = body["agent_message"].lower()
    for word in ("score", "speaker", "synthetic", "spoof", "l1", "l2", "l4", "probab", "%", "0."):
        assert word not in msg


# ------------------------------------------------------------- input checks
def test_unknown_call_404(client):
    assert client.get("/calls/nope").status_code == 404
    assert client.post("/calls/nope/transcript", json={"text": "x"}).status_code == 404


def test_duplicate_call_id_409(client):
    start(client)
    r = client.post("/calls", json={"call_id": "c1", "customer_id": "x", "request_type": "balance", "enrolled": True})
    assert r.status_code == 409


def test_bad_audio_rejected(client):
    start(client)
    assert client.post("/calls/c1/audio", json={"pcm_b64": "!!!"}).status_code == 422
    assert client.post("/calls/c1/audio", json={"pcm_b64": "AA=="}).status_code == 422  # odd byte count
    assert client.post("/calls/c1/audio", json={"pcm_b64": ""}).status_code == 422
    assert client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 44100}).status_code == 422


def test_unknown_request_type_rejected(client):
    r = client.post("/calls", json={"customer_id": "x", "request_type": "wire_transfer", "enrolled": True})
    assert r.status_code == 422


def test_resample_8k_to_16k_doubles_length():
    pcm = __import__("base64").b64decode(tone_b64(0.1, 8000))
    out = audio.to_16k(pcm, 8000)
    assert len(out) == 2 * len(pcm)
    assert audio.to_16k(pcm, 16000) == pcm


# ---------------------------------------------------------------- analyst
def held_call(client, call_id="c1"):
    start(client, call_id=call_id, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    speak(client, call_id, text="urgent jaldi")


def test_analyst_can_release(client):
    held_call(client)
    r = client.post("/cases/c1/release", headers=ANALYST, json={"note": "customer confirmed by branch"})
    assert r.status_code == 200
    assert "released" in r.json()["agent_message"]
    d = client.get("/cases/c1", headers=ANALYST).json()
    assert d["analyst_decision"]["user"] == "analyst-1" and d["analyst_decision"]["decision"] == "released"


def test_analyst_can_escalate(client):
    held_call(client)
    r = client.post("/cases/c1/escalate", headers=ANALYST)
    assert r.status_code == 200 and "escalated" in r.json()["agent_message"]


@pytest.mark.parametrize("action", ["release", "escalate"])
@pytest.mark.parametrize("headers", [AGENT, HEAD1])
def test_only_analyst_may_release_or_escalate(client, action, headers):
    held_call(client)
    assert client.post(f"/cases/c1/{action}", headers=headers).status_code == 403
    assert client.get("/calls/c1").json()["status"] == "held"


@pytest.mark.parametrize("headers", [{}, {"X-User": "a"}, {"X-User": "a", "X-Role": "root"}])
def test_missing_or_unknown_identity_is_401(client, headers):
    held_call(client)
    assert client.post("/cases/c1/release", headers=headers).status_code == 401


def test_case_must_be_held_and_decided_once(client):
    start(client)
    speak(client)
    assert client.post("/cases/c1/release", headers=ANALYST).status_code == 409  # Clear call
    held_call(client, "c2")
    assert client.post("/cases/c2/release", headers=ANALYST).status_code == 200
    assert client.post("/cases/c2/escalate", headers=ANALYST).status_code == 409
    assert client.post("/cases/zzz/release", headers=ANALYST).status_code == 404


def test_case_detail_restricted_and_has_scores(client):
    held_call(client)
    assert client.get("/cases/c1", headers=AGENT).status_code == 403
    d = client.get("/cases/c1", headers=ANALYST).json()
    assert d["layers"]["l2"]["prob"] > 0.9 and d["models"]["l2"] == "mock-l2-0"
    assert d["config_is_placeholder"] is True
    assert "customer" not in json.dumps(d).replace("customer_ref", "")  # raw customer id not stored


# ------------------------------------------------------------- evidence/audit
def test_full_call_is_hash_chained_and_verifiable(client, ev_path, clock):
    start(client, request_type="limit_change")
    d = digits_of(speak(client))
    answer(client, clock, "c1", "0 0 0 0 0 0" if d != list("000000") else "1 1 1 1 1 1")
    client.post("/calls/c1/app-response", json={"result": "deny"})
    client.post("/cases/c1/escalate", headers=ANALYST)
    r = client.get("/audit/verify", headers=ANALYST).json()
    assert r["ok"] and r["records"] >= 5
    events = [x["event"] for x in map(json.loads, ev_path.read_text().splitlines())]
    assert events[:2] == ["call_started", "band_decided"]
    assert events[-3:] == ["challenge_result", "app_response", "analyst_escalated"]
    final = json.loads(ev_path.read_text().splitlines()[-1])["data"]
    assert final["band"] == "Hold" and final["challenge"]["outcome"] == "fail"
    assert final["analyst_decision"]["decision"] == "escalated"
    assert set(final["challenge"]) == {"outcome", "reason", "reply_seconds", "digits_heard", "issued_at"}  # expected digits not logged


def test_audit_verify_detects_tampering(client, ev_path):
    held_call(client)
    assert client.get("/audit/verify", headers=ANALYST).json()["ok"]
    text = ev_path.read_text().replace('"band": "Hold"', '"band": "Clear"')
    ev_path.write_text(text)
    r = client.get("/audit/verify", headers=ANALYST).json()
    assert not r["ok"] and r["bad_seq"] is not None


def test_audit_verify_needs_privileged_role(client):
    assert client.get("/audit/verify", headers=AGENT).status_code == 403
    assert client.get("/audit/verify", headers=HEAD1).status_code == 200


# ------------------------------------------------------- threshold changes
def propose(client, headers=HEAD1, layer="l2", weak=0.7, strong=0.95):
    return client.post("/config/thresholds", headers=headers,
                       json={"layer": layer, "weak": weak, "strong": strong, "reason": "recalibration"})


def current(client, layer="l2"):
    return client.get("/config/thresholds", headers=ANALYST).json()["thresholds"][layer]


def test_threshold_change_needs_two_distinct_approvers(client):
    before = current(client)
    p = propose(client)
    assert p.status_code == 201 and p.json()["status"] == "pending"
    pid = p.json()["proposal_id"]

    r1 = client.post(f"/config/thresholds/{pid}/approve", headers=HEAD1)
    assert r1.json()["status"] == "pending" and current(client) == before

    again = client.post(f"/config/thresholds/{pid}/approve", headers=HEAD1)  # same person twice
    assert again.status_code == 409 and current(client) == before

    r2 = client.post(f"/config/thresholds/{pid}/approve", headers=HEAD2)
    assert r2.json()["status"] == "applied" and r2.json()["approvers"] == ["head-1", "head-2"]
    assert current(client) == {"weak": 0.7, "strong": 0.95}

    assert client.post(f"/config/thresholds/{pid}/approve", headers=HEAD2).status_code == 409


def test_threshold_change_is_role_gated(client):
    for h in (AGENT, ANALYST):
        assert propose(client, headers=h).status_code == 403
    pid = propose(client).json()["proposal_id"]
    for h in (AGENT, ANALYST):
        assert client.post(f"/config/thresholds/{pid}/approve", headers=h).status_code == 403
    assert current(client) == {"weak": 0.35, "strong": 0.75}


def test_threshold_change_validation_and_unknown_proposal(client):
    assert propose(client, weak=0.9, strong=0.5).status_code == 422
    assert propose(client, layer="l3").status_code == 422
    assert client.post("/config/thresholds/nope/approve", headers=HEAD1).status_code == 409


def test_applied_threshold_changes_later_decisions_and_is_logged(client, ev_path):
    start(client, call_id="before", mock_l1_cosine=0.55, mock_l2_spoof=0.55)
    assert speak(client, "before")["band"] == "Step up"
    pid = propose(client, layer="l2", weak=0.8, strong=0.95).json()["proposal_id"]
    client.post(f"/config/thresholds/{pid}/approve", headers=HEAD1)
    client.post(f"/config/thresholds/{pid}/approve", headers=HEAD2)
    start(client, call_id="after", mock_l1_cosine=0.55, mock_l2_spoof=0.55)
    assert speak(client, "after")["band"] == "Clear"  # only L1 weak now
    assert client.get("/cases/after", headers=ANALYST).json()["thresholds_used"]["l2"]["weak"] == 0.8
    events = [json.loads(l)["event"] for l in ev_path.read_text().splitlines()]
    assert events.count("threshold_approved") == 1 and "threshold_applied" in events
    assert verify_chain(ev_path).ok


# ---------------------------------------------------------------- websocket
def test_websocket_pushes_band_updates(client):
    start(client)
    with client.websocket_connect("/ws/agent/c1") as ws:
        first = ws.receive_json()
        assert first["band"] is None and first["status"] == "collecting"
        speak(client)
        update = ws.receive_json()
        assert update["band"] == "Clear" and "agent_message" in update and "score" not in json.dumps(update)


def test_websocket_pushes_step_up_then_hold(client, clock):
    start(client, request_type="limit_change")
    with client.websocket_connect("/ws/agent/c1") as ws:
        ws.receive_json()
        v = speak(client)
        assert ws.receive_json()["band"] == "Step up"
        answer(client, clock, "c1", "sorry what")
        assert ws.receive_json()["band"] == "Hold"
    assert v["challenge_pending"]


def test_websocket_unknown_call_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/agent/missing"):
            pass


# ------------------------------------------------------------ real adapters
def test_real_adapters_import_and_construct_without_ml_packages():
    from service import scorers
    scorers.SpeechBrainEcapaSpeakerScorer(lambda cid: [0.0])
    scorers.AasistSpoofScorer("/nonexistent.pt")
    scorers.FasterWhisperASR()
    assert isinstance(scorers.MockSpeakerScorer(), scorers.SpeakerScorer)
    assert isinstance(scorers.MockSpoofScorer(), scorers.SpoofScorer)
    assert isinstance(scorers.MockASR(), scorers.ASR)
