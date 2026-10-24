"""Regression tests for gaps found in review: silent Clear on bad scores, message sequence,
per-account digit attempt cap, app-timeout semantics, approver identity, evidence 'who decided'."""
import json

import pytest
from fastapi.testclient import TestClient

from service.api import create_app
from service.config import load_config
from service.evidence import verify_chain
from service.models import CallView
from service.roles import Principal, ProposalError, Role, ThresholdChangeManager
from service.testing import FakeClock, tone_b64

ANALYST = {"X-User": "analyst-1", "X-Role": "analyst"}


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


def start(client, call_id="c1", customer="cust", request_type="balance", enrolled=True, flags=None, **meta):
    r = client.post("/calls", json={"call_id": call_id, "customer_id": customer, "request_type": request_type,
                                    "enrolled": enrolled, "bank_flags": flags or {}, "metadata": meta})
    assert r.status_code == 201, r.text
    return r.json()


def speak(client, call_id="c1", text="mera balance bata dijiye"):
    r1 = client.post(f"/calls/{call_id}/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    r1.raise_for_status()
    r = client.post(f"/calls/{call_id}/transcript", json={"text": text})
    r.raise_for_status()
    return r.json()


def wrong_answer(client, clock, call_id):
    clock.advance(4.0)
    r = client.post(f"/calls/{call_id}/challenge/answer", json={"text": "no idea"})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------- bad scorer output must not become Clear
@pytest.mark.parametrize("key,value", [
    ("mock_l2_spoof", "nan"), ("mock_l2_spoof", "-inf"), ("mock_l2_spoof", "inf"),
    ("mock_l2_spoof", -0.5), ("mock_l2_spoof", 1.5),
    ("mock_l1_cosine", "nan"), ("mock_l1_cosine", "inf"), ("mock_l1_cosine", 3.0),
])
def test_out_of_contract_score_fails_open_not_clear(client, key, value):
    start(client, request_type="balance", **{key: value})
    v = speak(client)
    assert v["band"] == "Unavailable" and v["status"] == "unavailable"
    assert "normal bank process" in v["agent_message"]
    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert detail["fail_open"]["reason"].startswith("model_error: ScorerError")


def test_scorer_returning_none_fails_open_not_500():
    from service.scorers import MockSpoofScorer

    class NoneScorer(MockSpoofScorer):
        def score(self, pcm, sample_rate, meta):
            return None

    import tempfile, os
    d = tempfile.mkdtemp()
    with TestClient(create_app(evidence_path=os.path.join(d, "e.jsonl"), l2=NoneScorer(), clock=FakeClock())) as c:
        start(c)
        assert speak(c)["band"] == "Unavailable"


def test_error_while_computing_bands_fails_open_visibly(client, monkeypatch):
    start(client)
    engine = client.app.state.engine

    def boom(*a, **k):
        raise RuntimeError("calibration blew up")

    monkeypatch.setattr(engine, "_decide", boom)
    v = speak(client)
    assert v["band"] == "Unavailable"
    assert client.get("/cases/c1", headers=ANALYST).json()["fail_open"]["reason"].startswith("scoring_error")


def test_good_scores_still_clear(client):
    start(client, mock_l1_cosine=1.0, mock_l2_spoof=0.0)
    assert speak(client)["band"] == "Clear"


# ----------------------------------------------------------- message sequence
def test_views_carry_a_sequence_that_only_goes_up(client, clock):
    s0 = start(client, request_type="limit_change")["seq"]
    s1 = speak(client)["seq"]
    s2 = wrong_answer(client, clock, "c1")["seq"]
    s3 = client.post("/calls/c1/app-response", json={"result": "timeout"}).json()["seq"]
    s4 = client.post("/cases/c1/release", headers=ANALYST, json={}).json()["seq"]
    assert s0 < s1 < s2 < s3 < s4
    assert client.get("/calls/c1").json()["seq"] == s4  # reads do not bump it


def test_websocket_ignores_stale_duplicate_and_keeps_newer_state(client, clock):
    start(client, request_type="limit_change")
    with client.websocket_connect("/ws/agent/c1") as ws:
        first = ws.receive_json()
        stale = CallView(call_id="c1", status="collecting", band=None, agent_message="old", seq=first["seq"])
        client.app.state.engine.notify(stale)  # late duplicate of the state already shown
        v = speak(client)
        update = ws.receive_json()
        assert update["seq"] == v["seq"] and update["band"] == "Step up"  # the stale one was skipped


def test_websocket_first_message_is_current_state_with_seq(client):
    started = start(client)
    with client.websocket_connect("/ws/agent/c1") as ws:
        assert ws.receive_json()["seq"] == started["seq"]


# ------------------------------------------------- challenge: counts and caps
def test_challenge_has_one_attempt_per_call(client, clock):
    start(client, request_type="limit_change")
    speak(client)
    wrong_answer(client, clock, "c1")
    r = client.post("/calls/c1/challenge/answer", json={"text": "1 2 3 4 5 6"})
    assert r.status_code == 409


def test_digit_prompt_names_the_configured_digit_count(clock, ev_path):
    cfg = load_config()
    cfg.challenge.digits = 8
    with TestClient(create_app(config=cfg, evidence_path=str(ev_path), clock=clock)) as c:
        start(c, request_type="limit_change")
        msg = speak(c)["agent_message"]
        assert "these eight digits:" in msg and len(msg.split(": ")[1].split()) == 8


def test_account_attempt_cap_sends_next_step_up_to_hold(client, clock):
    cap = client.app.state.engine.cfg.challenge.max_failed_attempts_per_account
    for i in range(cap):
        cid = f"c{i}"
        start(client, call_id=cid, request_type="limit_change")
        assert speak(client, cid)["band"] == "Step up"
        assert wrong_answer(client, clock, cid)["band"] == "Hold"
    start(client, call_id="next", request_type="limit_change")
    v = speak(client, "next")
    assert v["band"] == "Hold" and not v["challenge_pending"] and v["app_prompt_pending"]
    assert "digits" not in v["agent_message"].lower()
    detail = client.get("/cases/next", headers=ANALYST).json()
    assert "l3_account_attempt_cap" in detail["reasons"] and detail["challenge"] is None


def test_account_attempt_cap_is_per_account_and_expires(client, clock):
    eng = client.app.state.engine
    cap = eng.cfg.challenge.max_failed_attempts_per_account
    for i in range(cap):
        start(client, call_id=f"a{i}", customer="alice", request_type="limit_change")
        speak(client, f"a{i}")
        wrong_answer(client, clock, f"a{i}")
    start(client, call_id="bob1", customer="bob", request_type="limit_change")
    assert speak(client, "bob1")["band"] == "Step up"  # other accounts unaffected
    clock.advance(eng.cfg.challenge.account_window_seconds + 1)
    start(client, call_id="alice-later", customer="alice", request_type="limit_change")
    assert speak(client, "alice-later")["band"] == "Step up"  # window has passed


def test_passed_challenges_do_not_use_up_the_account_cap(client, clock):
    cap = client.app.state.engine.cfg.challenge.max_failed_attempts_per_account
    for i in range(cap + 1):
        cid = f"p{i}"
        start(client, call_id=cid, request_type="limit_change")
        v = speak(client, cid)
        clock.advance(4.0)
        out = client.post(f"/calls/{cid}/challenge/answer", json={"text": " ".join(v["agent_message"].split(": ")[1].rstrip(".").split())}).json()
        assert out["status"] == "challenge_passed"


# ------------------------------------------------------------- app prompt
@pytest.mark.parametrize("result,confirmed", [("approve", True), ("deny", False), ("timeout", False)])
def test_only_an_approval_counts_as_confirmed_and_nothing_releases(client, result, confirmed):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    speak(client, text="urgent jaldi karo")
    v = client.post("/calls/c1/app-response", json={"result": result}).json()
    assert v["band"] == "Hold" and v["status"] == "held" and not v["app_prompt_pending"]
    app = client.get("/cases/c1", headers=ANALYST).json()["app_confirmation"]
    assert app["result"] == result and app["confirmed"] is confirmed


# ------------------------------------------------------- approver identity
def test_same_person_under_a_different_spelling_is_not_a_second_approver():
    applied = []
    mgr = ThresholdChangeManager(lambda *a: applied.append(a))
    head = Principal("Head-1", Role.FRAUD_HEAD)
    prop = mgr.propose(head, "l2", 0.5, 0.9, "recal")
    mgr.approve(head, prop.proposal_id)
    with pytest.raises(ProposalError):
        mgr.approve(Principal("  head-1 ", Role.FRAUD_HEAD), prop.proposal_id)
    assert applied == [] and prop.status == "pending"
    mgr.approve(Principal("head-2", Role.FRAUD_HEAD), prop.proposal_id)
    assert len(applied) == 1 and prop.status == "applied"


def test_failed_apply_does_not_leave_a_counted_approval():
    def apply(layer, weak, strong):
        raise ValueError("unknown layer")

    mgr = ThresholdChangeManager(apply)
    prop = mgr.propose(Principal("h1", Role.FRAUD_HEAD), "zz", 0.5, 0.9, "x")
    mgr.approve(Principal("h1", Role.FRAUD_HEAD), prop.proposal_id)
    with pytest.raises(ValueError):
        mgr.approve(Principal("h2", Role.FRAUD_HEAD), prop.proposal_id)
    assert prop.approvers == ["h1"] and prop.status == "pending"


# ---------------------------------------------------------------- evidence
def test_evidence_records_who_decided(client, ev_path):
    start(client, flags={"new_device": True, "new_payee": True}, mock_l2_spoof=0.9)
    speak(client, text="urgent jaldi karo")
    assert client.get("/cases/c1", headers=ANALYST).json()["decided_by"] == "system"
    client.post("/cases/c1/release", headers=ANALYST, json={"note": "ok"})
    assert client.get("/cases/c1", headers=ANALYST).json()["decided_by"] == "analyst-1"
    last = [r for r in map(json.loads, ev_path.read_text().splitlines()) if r["call_id"] == "c1"][-1]
    assert last["event"] == "analyst_released" and last["data"]["decided_by"] == "analyst-1"
    assert last["data"]["view_seq"] >= 3
    assert verify_chain(ev_path).ok
