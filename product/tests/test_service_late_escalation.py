import pytest
from starlette.testclient import TestClient
from service.api import create_app
from service.models import Band
from service.testing import FakeClock, tone_b64

ANALYST = {"X-User": "alice", "X-Role": "analyst"}


class DynamicSpoofScorer:
    model_version = "dyn-l2"
    def __init__(self, initial_score: float = 0.05):
        self.current_score = initial_score

    def score(self, pcm, sample_rate, meta):
        return self.current_score


def test_late_window_strong_l2_escalates_clear_to_step_up_and_queues_review():
    clock = FakeClock()
    dynamic_l2 = DynamicSpoofScorer(initial_score=0.05)
    app = create_app(clock=clock, l2=dynamic_l2)
    client = TestClient(app)

    # Start a low-risk call that becomes Clear
    client.post("/calls", json={"call_id": "late1", "customer_id": "cust1", "request_type": "balance", "enrolled": False})
    client.post("/calls/late1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    v1 = client.post("/calls/late1/transcript", json={"text": "mera balance bata do"}).json()
    assert v1["band"] == "Clear"
    assert v1["status"] == "clear"

    # Later window audio arrives where voice changer engages (strong score: 0.95)
    dynamic_l2.current_score = 0.95
    v2 = client.post("/calls/late1/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    # Escalated to Step up!
    assert v2["band"] == "Step up"
    assert v2["challenge_pending"] is True

    # Review queue must hold an entry for this call
    reviews = client.get("/reviews", headers=ANALYST).json()
    assert any(r["call_id"] == "late1" and r["reason"] == "l2_strong_late_window" for r in reviews)


def test_late_window_cannot_lower_band():
    clock = FakeClock()
    dynamic_l2 = DynamicSpoofScorer(initial_score=0.1)
    app = create_app(clock=clock, l2=dynamic_l2)
    client = TestClient(app)

    # Start a call that steps up due to sensitive request with an enrolled customer
    client.post("/calls", json={"call_id": "late2", "customer_id": "cust2", "request_type": "limit_change", "enrolled": True})
    client.post("/calls/late2/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})
    v1 = client.post("/calls/late2/transcript", json={"text": "limit badhana hai"}).json()
    assert v1["band"] == "Step up"

    # Subsequent clean window audio cannot lower the band to Clear
    dynamic_l2.current_score = 0.01
    v2 = client.post("/calls/late2/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000}).json()
    assert v2["band"] == "Step up"
