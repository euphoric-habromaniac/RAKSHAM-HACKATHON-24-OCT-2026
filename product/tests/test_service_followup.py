"""Follow-up changes: post-call review after a passed challenge with a strong L2 signal,
Step up (not fail open) when scoring is unavailable on a sensitive request, and the
explicit AASIST logit order."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from service.api import create_app
from service.evidence import verify_chain
from service.scorers import AASIST_LOGIT_ORDER, AASIST_SPOOF_INDEX, AasistSpoofScorer, spoof_probability
from service.testing import FakeClock, tone_b64

AGENT = {"X-User": "agent-1", "X-Role": "agent"}
ANALYST = {"X-User": "analyst-1", "X-Role": "analyst"}
HEAD = {"X-User": "head-1", "X-Role": "fraud_head"}
DIGITS = re.compile(r"(\d(?: \d){5})")
SENSITIVE = ["limit_change", "new_payee", "mobile_change", "device_change"]


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


def start(client, call_id="c1", customer="cust", request_type="balance", enrolled=True, **meta):
    r = client.post("/calls", json={"call_id": call_id, "customer_id": customer, "request_type": request_type,
                                    "enrolled": enrolled, "metadata": meta})
    assert r.status_code == 201, r.text
    return r.json()


def speak(client, call_id="c1"):
    client.post(f"/calls/{call_id}/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).raise_for_status()
    r = client.post(f"/calls/{call_id}/transcript", json={"text": "mera balance bata dijiye"})
    r.raise_for_status()
    return r.json()


def answer(client, clock, call_id, text, after=4.0):
    clock.advance(after)
    r = client.post(f"/calls/{call_id}/challenge/answer", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def pass_challenge(client, clock, call_id, view):
    return answer(client, clock, call_id, DIGITS.search(view["agent_message"]).group(1))


# ---------------------------------------- 1. strong L2 then a passed challenge
def test_strong_l2_then_pass_continues_but_is_queued_for_review(client, clock, ev_path):
    start(client, mock_l2_spoof=0.9)
    v = speak(client)
    assert v["band"] == "Step up"
    out = pass_challenge(client, clock, "c1", v)
    assert out["status"] == "challenge_passed" and out["band"] == "Step up"  # agent carries on, no pause

    queue = client.get("/reviews", headers=ANALYST).json()
    assert [q["call_id"] for q in queue] == ["c1"]
    assert queue[0]["reason"] == "l2_strong_after_pass" and queue[0]["status"] == "open"

    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert detail["review_flag"]["reason"] == "l2_strong_after_pass"
    assert any(a["action"] == "flagged_for_post_call_review" for a in detail["actions"])
    last = [r for r in map(json.loads, ev_path.read_text().splitlines()) if r["call_id"] == "c1"][-1]
    assert last["event"] == "challenge_result" and last["data"]["review_flag"]["reason"] == "l2_strong_after_pass"
    assert verify_chain(ev_path).ok


def test_review_flag_is_never_shown_to_the_agent(client, clock):
    start(client, mock_l2_spoof=0.9)
    out = pass_challenge(client, clock, "c1", speak(client))
    assert set(out) == {"call_id", "status", "band", "agent_message", "challenge_pending", "app_prompt_pending", "seq"}
    assert out["agent_message"] == "Digits confirmed. Continue with the standard process for this request."
    assert "l2" not in json.dumps(client.get("/calls/c1").json()).lower()
    assert client.get("/reviews", headers=AGENT).status_code == 403
    assert client.get("/reviews", headers=HEAD).status_code == 200


def test_pass_without_strong_l2_is_not_queued(client, clock):
    # Ordinary request with two weak signals or strong L1: passing challenge does not queue review
    start(client, call_id="weak", request_type="balance", mock_l1_cosine=0.55, mock_l2_spoof=0.55)
    pass_challenge(client, clock, "weak", speak(client, "weak"))
    start(client, call_id="l1", request_type="balance", mock_l1_cosine=-0.5)
    pass_challenge(client, clock, "l1", speak(client, "l1"))
    assert client.get("/reviews", headers=ANALYST).json() == []

    # Review rule: sensitive request that passed Step up DOES queue a next-day review entry
    start(client, call_id="sens", request_type="limit_change")
    pass_challenge(client, clock, "sens", speak(client, "sens"))
    reviews = client.get("/reviews", headers=ANALYST).json()
    assert len(reviews) == 1
    assert reviews[0]["call_id"] == "sens"
    assert reviews[0]["reason"] == "sensitive_request_step_up_passed"


def test_strong_l2_with_failed_challenge_is_a_hold_not_a_review_item(client, clock):
    start(client, mock_l2_spoof=0.9)
    speak(client)
    assert answer(client, clock, "c1", "no idea")["band"] == "Hold"
    assert client.get("/reviews", headers=ANALYST).json() == []


# ------------------------------- 2. scoring unavailable on a sensitive request
@pytest.mark.parametrize("request_type", SENSITIVE)
def test_scoring_failure_on_sensitive_request_starts_step_up(client, request_type, ev_path):
    start(client, request_type=request_type, mock_error="l2")
    r = client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    v = r.json()
    assert v["band"] == "Step up" and v["challenge_pending"] and v["status"] == "challenge_pending"
    assert len(DIGITS.search(v["agent_message"]).group(1).split()) == 6
    detail = client.get("/cases/c1", headers=ANALYST).json()
    assert detail["reasons"] == ["scoring_unavailable_sensitive"]
    assert detail["fail_open"]["reason"].startswith("model_error") and detail["fail_open"]["handled_as"] == "step_up"
    events = [json.loads(l)["event"] for l in ev_path.read_text().splitlines()]
    assert "scoring_unavailable_step_up" in events and verify_chain(ev_path).ok


def test_ordinary_request_still_fails_open_when_scoring_fails(client):
    start(client, request_type="balance", mock_error="l2")
    v = client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    assert v["band"] == "Unavailable" and not v["challenge_pending"]


@pytest.mark.parametrize("bad", ["nan", "inf", -0.5])
def test_out_of_contract_score_on_sensitive_request_steps_up(client, bad):
    start(client, request_type="new_payee", mock_l2_spoof=bad)
    assert speak(client)["band"] == "Step up"


def test_late_scoring_on_sensitive_request_steps_up_on_read(client, clock):
    start(client, request_type="mobile_change")
    client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    clock.advance(11)
    v = client.get("/calls/c1").json()
    assert v["band"] == "Step up" and v["challenge_pending"]
    assert client.get("/cases/c1", headers=ANALYST).json()["reasons"] == ["scoring_unavailable_sensitive"]


def test_unavailable_then_challenge_pass_continues_and_is_not_review_queued(client, clock):
    start(client, request_type="balance", mock_error="l1")
    v = client.post("/calls/c1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    # ordinary request failing open on error steps to Unavailable, but if started on sensitive it queues
    start(client, call_id="c2", request_type="limit_change", mock_error="l1")
    v2 = client.post("/calls/c2/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    out = pass_challenge(client, clock, "c2", v2)
    assert out["status"] == "challenge_passed" and out["band"] == "Step up"
    reviews = client.get("/reviews", headers=ANALYST).json()
    assert any(r["call_id"] == "c2" and r["reason"] == "sensitive_request_step_up_passed" for r in reviews)


def test_unavailable_then_failed_or_unclear_challenge_holds_never_blocks(client, clock):
    start(client, call_id="a", request_type="limit_change", mock_error="l2")
    client.post("/calls/a/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    v = answer(client, clock, "a", "sorry what")
    assert v["band"] == "Hold" and v["app_prompt_pending"] and "block" not in v["agent_message"].lower()
    start(client, call_id="b", request_type="limit_change", mock_error="l2")
    first = client.post("/calls/b/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    digits = DIGITS.search(first["agent_message"]).group(1).split()
    wrong = [str((int(digits[0]) + 1) % 10)] + digits[1:]
    assert answer(client, clock, "b", " ".join(wrong))["band"] == "Hold"


def test_account_attempt_cap_applies_when_scoring_is_unavailable(client, clock):
    cap = client.app.state.engine.cfg.challenge.max_failed_attempts_per_account
    for i in range(cap):
        start(client, call_id=f"f{i}", request_type="limit_change", mock_error="l2")
        client.post(f"/calls/f{i}/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
        assert answer(client, clock, f"f{i}", "sorry what")["band"] == "Hold"
    start(client, call_id="next", request_type="limit_change", mock_error="l2")
    v = client.post("/calls/next/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    assert v["band"] == "Hold" and not v["challenge_pending"] and v["app_prompt_pending"]
    reasons = client.get("/cases/next", headers=ANALYST).json()["reasons"]
    assert reasons == ["scoring_unavailable_sensitive", "l3_account_attempt_cap"]


def test_asr_failure_during_the_challenge_still_fails_open(client, clock):
    start(client, request_type="limit_change", mock_error="asr")
    speak(client)
    clock.advance(4)
    r = client.post("/calls/c1/challenge/answer", json={"pcm_b64": tone_b64()})
    assert r.json()["band"] == "Unavailable"


# ---------------------------------------------------- 3. AASIST logit order
def test_logit_order_constant_matches_eval_convention():
    assert AASIST_LOGIT_ORDER == ("spoof", "bonafide") and AASIST_SPOOF_INDEX == 0
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "eval" / "run_aasist.py").read_text()
    assert "out[:, 1]" in src and "bona fide logit" in src  # eval reads index 1 as bona fide


def test_spoof_probability_uses_the_spoof_index():
    assert spoof_probability([4.0, -4.0]) > 0.99          # default: index 0 is spoof
    assert spoof_probability([-4.0, 4.0]) < 0.01
    assert spoof_probability([4.0, -4.0], spoof_index=1) < 0.01
    assert spoof_probability([0.0, 0.0]) == pytest.approx(0.5)
    assert spoof_probability([1000.0, -1000.0]) == pytest.approx(1.0)  # stable at extremes
    with pytest.raises(Exception):
        spoof_probability([1.0, 2.0, 3.0])


def test_aasist_scorer_with_fake_model_scores_spoof_high_and_bonafide_low():
    torch = pytest.importorskip("torch")

    class FakeModel:
        """AASIST-ordered logits (spoof, bona fide): a loud clip is spoof, a quiet one is bona fide."""
        def __call__(self, wav):
            loud = float(wav.abs().max()) > 0.1
            return torch.tensor([[3.0, -3.0]] if loud else [[-3.0, 3.0]])

    scorer = AasistSpoofScorer("/unused.pt")
    scorer._model = FakeModel()
    import struct
    spoof_clip = struct.pack("<8h", *([20000, -20000] * 4))
    bona_clip = struct.pack("<8h", *([100, -100] * 4))
    assert scorer.score(spoof_clip, 16000, {}) > 0.99
    assert scorer.score(bona_clip, 16000, {}) < 0.01
    flipped = AasistSpoofScorer("/unused.pt", spoof_index=1)
    flipped._model = FakeModel()
    assert flipped.score(spoof_clip, 16000, {}) < 0.01
