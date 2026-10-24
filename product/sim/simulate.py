"""Finale demo skeleton: three scripted calls through the HTTP API with mock scorers.

    python sim/simulate.py [--only N] [--evidence PATH]

Runs in-process (FastAPI TestClient) with a manual clock, so reply times are
set by the script and the run is deterministic apart from the random digits.
Scores come from the mock scorers; nothing here measures real detection.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from service.api import create_app  # noqa: E402
from service.testing import FakeClock, tone_b64  # noqa: E402

ANALYST = {"X-User": "analyst-02", "X-Role": "analyst"}
DIGITS_RE = re.compile(r"(\d(?: \d){5})")


class Run:
    def __init__(self, client: TestClient, clock: FakeClock, call_id: str):
        self.c, self.clock, self.call_id = client, clock, call_id
        self.t0 = clock()

    def say(self, who: str, text: str) -> None:
        print(f"  [t+{self.clock() - self.t0:5.1f}s] {who:<8} {text}")

    def step(self, dt: float, who: str, text: str, method: str, path: str, **kw: Any) -> Dict[str, Any]:
        self.clock.advance(dt)
        r = self.c.request(method, path, **kw)
        r.raise_for_status()
        body = r.json()
        self.say(who, text)
        if "agent_message" in body:
            self.say("AGENT UI", f"[{body['band'] or 'pending'}] {body['agent_message']}")
        return body


def start(run: Run, **body: Any) -> None:
    r = run.c.post("/calls", json={"call_id": run.call_id, **body})
    r.raise_for_status()
    flags = [k for k, v in body.get("bank_flags", {}).items() if v] or "none"
    run.say("bank", f"call started: request={body['request_type']} enrolled={body['enrolled']} flags={flags}")


def caller_audio(run: Run, dt: float = 1.0) -> Dict[str, Any]:
    return run.step(dt, "caller", "speaks (8 kHz audio chunk, resampled to 16 kHz)", "POST",
                    f"/calls/{run.call_id}/audio", json={"pcm_b64": tone_b64(), "sample_rate": 8000})


def caller_text(run: Run, text: str, dt: float = 0.5) -> Dict[str, Any]:
    return run.step(dt, "ASR", f'transcript: "{text}"', "POST", f"/calls/{run.call_id}/transcript",
                    json={"text": text})


def digits_from(message: str) -> List[str]:
    m = DIGITS_RE.search(message)
    assert m, "agent message carried no digits"
    return m.group(1).split()


def scenario_genuine(c: TestClient, clock: FakeClock) -> None:
    print("\n=== 1. Genuine caller, balance enquiry (expect Clear) ===")
    r = Run(c, clock, "sim-genuine")
    start(r, customer_id="cust-1001", request_type="balance", enrolled=True,
          metadata={"mock_l1_cosine": 0.82, "mock_l2_spoof": 0.04})
    caller_audio(r)
    caller_text(r, "mera balance bata dijiye")


def scenario_clone(c: TestClient, clock: FakeClock) -> None:
    print("\n=== 2. Pre-recorded clone, limit change (Step up -> fails digits -> Hold -> app deny) ===")
    r = Run(c, clock, "sim-clone")
    start(r, customer_id="cust-1002", request_type="limit_change", enrolled=True,
          metadata={"mock_l1_cosine": 0.55, "mock_l2_spoof": 0.55})
    caller_audio(r)
    view = caller_text(r, "mujhe card ki limit badhani hai")
    heard = digits_from(view["agent_message"])
    wrong = heard[1:] + heard[:1]
    if wrong == heard:  # all digits equal: rotate does nothing, so change one
        wrong[0] = str((int(wrong[0]) + 1) % 10)
    r.step(4.0, "caller", "plays a pre-recorded reply that does not match: " + " ".join(wrong), "POST",
           f"/calls/{r.call_id}/challenge/answer", json={"text": " ".join(wrong)})
    r.step(20.0, "bank app", "customer taps Deny on the push prompt", "POST",
           f"/calls/{r.call_id}/app-response", json={"result": "deny"})
    r.step(30.0, "analyst", "escalates the case", "POST", f"/cases/{r.call_id}/escalate",
           headers=ANALYST, json={"note": "customer denied in app"})


def scenario_voice_changer(c: TestClient, clock: FakeClock) -> None:
    print("\n=== 3. Live voice changer, new payee (Hold + app prompt) ===")
    r = Run(c, clock, "sim-changer")
    start(r, customer_id="cust-1003", request_type="new_payee", enrolled=True,
          bank_flags={"new_device": True, "new_payee": True},
          metadata={"mock_l1_cosine": 0.72, "mock_l2_spoof": 0.90})
    caller_audio(r)
    caller_text(r, "urgent hai, jaldi payee add karo warna account block ho jayega")
    r.step(25.0, "bank app", "prompt times out, no reply from the customer", "POST",
           f"/calls/{r.call_id}/app-response", json={"result": "timeout"})
    r.step(60.0, "analyst", "escalates the case (no app confirmation)", "POST",
           f"/cases/{r.call_id}/escalate", headers=ANALYST, json={"note": "no app confirmation"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", type=int, choices=(1, 2, 3), help="run a single scenario")
    ap.add_argument("--evidence", help="evidence log path (default: temp file)")
    args = ap.parse_args()

    evidence = args.evidence or str(Path(tempfile.mkdtemp(prefix="asli-sim-")) / "evidence.jsonl")
    clock = FakeClock()
    app = create_app(evidence_path=evidence, clock=clock)
    scenarios = {1: scenario_genuine, 2: scenario_clone, 3: scenario_voice_changer}
    with TestClient(app) as client:
        for n, fn in scenarios.items():
            if args.only in (None, n):
                fn(client, clock)
        print("\n=== Audit ===")
        v = client.get("/audit/verify", headers=ANALYST).json()
        print(f"  evidence log: {evidence}")
        print(f"  chain ok={v['ok']} records={v['records']} head={v['head_hash'][:16]}...")
        if args.only in (None, 2):
            case = client.get("/cases/sim-clone", headers=ANALYST).json()
            print("  analyst view of call 2, calibrated scores (never shown to the agent):")
            for name, s in case["layers"].items():
                print(f"    {name}: raw={s['raw']:.2f} p={s['prob']:.2f} {s['strength']}")
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
