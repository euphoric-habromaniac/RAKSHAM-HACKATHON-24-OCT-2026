"""Call orchestration: scoring, policy, challenge, app confirmation, analyst actions.

Framework-free so it can be tested without HTTP. All state is in memory; the
evidence log is the durable record.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import audio, challenge as chal, policy
from .alerts import AlertSink
from .calibration import Platt
from .cases import CaseStore
from .config import ServiceConfig
from .evidence import EvidenceLog, iso
from .models import (AppResult, BankFlags, Band, CallView, L3Outcome, LayerScore,
                     RequestType, StartCallRequest, Strength)
from .roles import Principal, Role, authorize
from .scorers import ASR, ScorerError, SpeakerScorer, SpoofScorer

log = logging.getLogger("asli.engine")
failopen_log = logging.getLogger("asli.failopen")


_COUNT_WORDS = {4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _checked_score(name: str, value: Any, lo: float, hi: float) -> float:
    """A scorer's raw output must be a finite number inside its contract range.

    NaN and -inf compare false/low against every threshold, so without this check
    a broken scorer would produce a silent Clear instead of the fail-open state.
    """
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ScorerError(f"{name} returned a non-numeric score: {value!r}") from exc
    tol = 1e-6
    if not math.isfinite(v) or not (lo - tol) <= v <= (hi + tol):
        raise ScorerError(f"{name} score outside its contract [{lo}, {hi}]: {v!r}")
    return v


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass
class Session:
    call_id: str
    customer_id: str
    request_type: RequestType
    enrolled: bool
    flags: BankFlags
    metadata: Dict[str, Any]
    started_at: float
    lock: threading.RLock = field(default_factory=threading.RLock)
    first_reply_at: Optional[float] = None
    decided_at: Optional[float] = None
    l1_values: List[float] = field(default_factory=list)
    l2_values: List[float] = field(default_factory=list)
    transcript: List[str] = field(default_factory=list)
    samples_scored: int = 0
    layers: Dict[str, LayerScore] = field(default_factory=dict)
    urgency_hits: List[str] = field(default_factory=list)
    thresholds_used: Dict[str, Dict[str, float]] = field(default_factory=dict)
    band: Optional[Band] = None
    status: str = "collecting"
    reasons: List[str] = field(default_factory=list)
    challenge: Optional[chal.Challenge] = None
    l3: Optional[Dict[str, Any]] = None
    app: Optional[Dict[str, Any]] = None
    analyst: Optional[Dict[str, Any]] = None
    seq: int = 0
    review: Optional[Dict[str, Any]] = None  # post-call analyst review flag; never shown to the agent
    fail_open: Optional[Dict[str, Any]] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    models: Dict[str, str] = field(default_factory=dict)


class CallEngine:
    def __init__(self, cfg: ServiceConfig, evidence: EvidenceLog, l1: SpeakerScorer,
                 l2: SpoofScorer, asr: ASR, clock: Callable[[], float] = time.time,
                 notify: Optional[Callable[[CallView], None]] = None,
                 cases: Optional[CaseStore] = None,
                 alerts: Optional[AlertSink] = None):
        self.cfg = cfg
        self.evidence = evidence
        self.l1, self.l2, self.asr = l1, l2, asr
        self.clock = clock
        self.notify = notify or (lambda _v: None)
        self.cases = cases or CaseStore()
        self.alerts = alerts or AlertSink()
        self.platt = {k: Platt.from_config(v.platt) for k, v in cfg.layers.items()}
        self.thresholds = {k: policy.Thresholds(v.weak, v.strong) for k, v in cfg.layers.items()}
        self._sessions: Dict[str, Session] = {}
        self._sessions_lock = threading.Lock()
        self._failed_attempts: Dict[str, List[float]] = {}  # customer_id -> times of failed/unclear L3 answers
        self._attempts_lock = threading.Lock()

    # ------------------------------------------------------------- plumbing
    def _get(self, call_id: str) -> Session:
        with self._sessions_lock:
            s = self._sessions.get(call_id)
        if s is None:
            raise NotFound(call_id)
        return s

    def _act(self, s: Session, action: str, **detail: Any) -> None:
        s.actions.append({"ts": iso(self.clock()), "action": action, **detail})

    def _snapshot(self, s: Session) -> Dict[str, Any]:
        return {
            "call_id": s.call_id,
            "customer_ref": hashlib.sha256(s.customer_id.encode()).hexdigest()[:16],
            "request_type": s.request_type.value,
            "enrolled": s.enrolled,
            "bank_flags": s.flags.model_dump(),
            "started_at": iso(s.started_at),
            "first_reply_at": iso(s.first_reply_at) if s.first_reply_at else None,
            "decided_at": iso(s.decided_at) if s.decided_at else None,
            "band": s.band.value if s.band else None,
            "status": s.status,
            "reasons": list(s.reasons),
            "layers": {k: v.model_dump(mode="json") for k, v in s.layers.items()},
            "urgency_terms_matched": list(s.urgency_hits),
            "thresholds_used": s.thresholds_used,
            "models": s.models,
            "config_version": self.cfg.version,
            "config_is_placeholder": self.cfg.placeholder,
            "challenge": s.l3,
            "app_confirmation": s.app,
            "analyst_decision": s.analyst,
            "decided_by": (s.analyst["user"] if s.analyst else ("system" if s.band is not None else None)),
            "view_seq": s.seq,
            "review_flag": s.review,
            "fail_open": s.fail_open,
            "actions": list(s.actions),
        }

    def _log(self, s: Session, event: str) -> None:
        s.seq += 1  # every logged event is a state change the agent view may show
        self.evidence.append(s.call_id, event, self._snapshot(s), self.clock())

    def _publish(self, s: Session) -> None:
        self.notify(self.view_of(s))

    # ----------------------------------------------------------------- views
    def agent_message(self, s: Session) -> str:
        if s.band is None:
            return "Checks in progress. Continue the conversation as normal."
        if s.band is Band.UNAVAILABLE:
            return "Voice checks are unavailable for this call. Continue with the normal bank process."
        if s.analyst:
            if s.analyst["decision"] == "released":
                return "An analyst has released this request. Continue with the standard process."
            return "An analyst has escalated this request. Do not process it. Follow the fraud team's instructions."
        if s.band is Band.CLEAR:
            return "No extra steps needed. Continue as normal."
        if s.band is Band.HOLD:
            return ("Request paused. The customer will get a prompt in the bank app. "
                    "An analyst will review.")
        if s.status == "challenge_passed":
            return "Digits confirmed. Continue with the standard process for this request."
        assert s.challenge is not None
        n = len(s.challenge.digits)
        return (f"Voice could not be confirmed. Ask the caller to repeat these {_COUNT_WORDS.get(n, str(n))} digits: "
                f"{chal.format_for_agent(s.challenge.digits)}.")

    def view_of(self, s: Session) -> CallView:
        return CallView(
            call_id=s.call_id, status=s.status, band=s.band, agent_message=self.agent_message(s),
            challenge_pending=s.status == "challenge_pending",
            app_prompt_pending=bool(s.app and s.app.get("result") is None),
            seq=s.seq,
        )

    def view(self, call_id: str) -> CallView:
        s = self._get(call_id)
        with s.lock:
            self._check_deadline(s)
            return self.view_of(s)

    def review_queue(self) -> List[Dict[str, Any]]:
        """Calls flagged for post-call analyst review (analyst-facing only)."""
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        out = []
        for s in sessions:
            with s.lock:
                if s.review is not None:
                    out.append({"call_id": s.call_id, "reason": s.review["reason"], "status": s.review["status"],
                                "flagged_at": s.review["at"], "band": s.band.value if s.band else None,
                                "layers": {k: v.model_dump(mode="json") for k, v in s.layers.items()}})
        return sorted(out, key=lambda r: r["flagged_at"])

    def evidence_snapshot(self, call_id: str) -> Dict[str, Any]:
        s = self._get(call_id)
        with s.lock:
            return self._snapshot(s)

    # ------------------------------------------------------------- lifecycle
    def start_call(self, req: StartCallRequest) -> CallView:
        call_id = req.call_id or uuid.uuid4().hex[:12]
        s = Session(call_id, req.customer_id, req.request_type, req.enrolled, req.bank_flags,
                    dict(req.metadata), self.clock())
        s.models = {"l2": self.l2.model_version, "asr": self.asr.model_version}
        if req.enrolled:
            s.models["l1"] = self.l1.model_version
        with self._sessions_lock:
            if call_id in self._sessions:
                raise Conflict("call_id already exists")
            self._sessions[call_id] = s
        with s.lock:
            self._act(s, "call_started")
            self._log(s, "call_started")
            return self.view_of(s)

    def _mark_first_reply(self, s: Session) -> None:
        if s.first_reply_at is None:
            s.first_reply_at = self.clock()

    def add_audio(self, call_id: str, pcm: bytes, sample_rate: int) -> CallView:
        s = self._get(call_id)
        with s.lock:
            if s.band is not None:
                if s.band in (Band.HOLD, Band.UNAVAILABLE):
                    return self.view_of(s)
                # Decision Dec2: evaluate later windows for synthetic anomalies
                try:
                    pcm16 = audio.to_16k(pcm, sample_rate)
                    l2_raw = _checked_score("L2", self.l2.score(pcm16, audio.TARGET_RATE, s.metadata), 0.0, 1.0)
                    s.l2_values.append(l2_raw)
                    s.samples_scored += len(pcm16) // 2
                    p_l2 = self.platt["l2"](l2_raw)
                    t_l2 = self.thresholds["l2"]
                    l2_str = policy.classify(p_l2, t_l2)
                    if l2_str is Strength.STRONG:
                        s.review = {"reason": "l2_strong_late_window", "status": "open", "at": iso(self.clock())}
                        self._act(s, "late_window_escalation", reason="l2_strong_late_window", l2_raw=l2_raw)
                        self._act(s, "flagged_for_post_call_review", reason="l2_strong_late_window")
                        if s.band is Band.CLEAR:
                            d = policy.Decision(Band.STEP_UP, {"l2": Strength.STRONG}, ["l2_strong_late_window"], needs_challenge=True)
                            self._apply(s, d, event="late_window_escalation")
                        elif s.band is Band.STEP_UP:
                            d = policy.Decision(Band.HOLD, {"l2": Strength.STRONG}, ["l2_strong_late_window"], needs_app_prompt=True)
                            self._apply(s, d, event="late_window_escalation")
                except Exception as exc:
                    log.warning("Late window scoring failed: %s", exc)
                return self.view_of(s)
            if self._check_deadline(s):
                return self.view_of(s)
            self._mark_first_reply(s)
            try:
                pcm16 = audio.to_16k(pcm, sample_rate)
                l2 = _checked_score("L2", self.l2.score(pcm16, audio.TARGET_RATE, s.metadata), 0.0, 1.0)
                l1 = None
                if s.enrolled:
                    l1 = _checked_score("L1", self.l1.score(s.customer_id, pcm16, audio.TARGET_RATE, s.metadata),
                                        -1.0, 1.0)
                s.l2_values.append(l2)
                if l1 is not None:
                    s.l1_values.append(l1)
                s.samples_scored += len(pcm16) // 2
            except Exception as exc:  # any scorer failure -> fail open
                self._fail_open(s, f"model_error: {type(exc).__name__}: {exc}")
                return self.view_of(s)
            self._maybe_decide(s)
            return self.view_of(s)

    def add_transcript(self, call_id: str, text: str) -> CallView:
        s = self._get(call_id)
        with s.lock:
            if s.band is not None or self._check_deadline(s):
                return self.view_of(s)
            self._mark_first_reply(s)
            s.transcript.append(text)
            self._maybe_decide(s)
            return self.view_of(s)

    # -------------------------------------------------------------- deciding
    def _check_deadline(self, s: Session) -> bool:
        """Fail open if initial scoring is still unfinished past the deadline."""
        if s.band is not None or s.first_reply_at is None:
            return False
        waited = self.clock() - s.first_reply_at
        if waited > self.cfg.deadline_seconds:
            self._fail_open(s, f"deadline_exceeded: {waited:.1f}s > {self.cfg.deadline_seconds:.1f}s")
            return True
        return False

    def sweep_deadlines(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            with s.lock:
                self._check_deadline(s)

    def _fail_open(self, s: Session, reason: str, allow_step_up: bool = True) -> None:
        if allow_step_up and s.request_type.value in set(self.cfg.sensitive_request_types):
            # No usable score on a sensitive request: do not skip the checks. Start the digit
            # challenge (Step up). A failed or unclear answer goes to Hold as usual; never a block.
            s.fail_open = {"reason": reason, "at": iso(self.clock()), "handled_as": "step_up"}
            self._act(s, "scoring_unavailable", reason=reason)
            failopen_log.warning("call %s: scoring unavailable on a sensitive request, starting digit challenge: %s",
                                 s.call_id, reason)
            d = policy.Decision(Band.STEP_UP, {}, ["scoring_unavailable_sensitive"], needs_challenge=True)
            self._apply(s, d, event="scoring_unavailable_step_up")
            return
        s.band, s.status, s.decided_at = Band.UNAVAILABLE, "unavailable", self.clock()
        s.fail_open = {"reason": reason, "at": iso(self.clock())}
        s.reasons = ["fail_open"]
        self._act(s, "fail_open", reason=reason)
        failopen_log.warning("call %s: failing open (normal bank process): %s", s.call_id, reason)
        self._log(s, "fail_open")
        self._publish(s)

    def _compute_layers(self, s: Session) -> None:
        raws: Dict[str, float] = {"l2": max(s.l2_values)}
        if s.enrolled:
            raws["l1"] = sum(s.l1_values) / len(s.l1_values)
        raws["l4"], s.urgency_hits = policy.context_raw_score(s.flags, " ".join(s.transcript), self.cfg.l4)
        s.layers = {}
        for name, raw in raws.items():
            p = self.platt[name](raw)
            if not math.isfinite(p):
                raise ValueError(f"{name} probability is not finite")
            s.layers[name] = LayerScore(raw=raw, prob=p, strength=policy.classify(p, self.thresholds[name]))
        s.thresholds_used = {k: {"weak": t.weak, "strong": t.strong} for k, t in self.thresholds.items()}

    def _decide(self, s: Session, l3: Optional[L3Outcome]) -> policy.Decision:
        return policy.decide(s.request_type.value, s.enrolled, {k: v.prob for k, v in s.layers.items()},
                             self.thresholds, self.cfg.sensitive_request_types, l3)

    def _maybe_decide(self, s: Session) -> None:
        if not (s.l2_values and s.transcript):
            return
        if self._check_deadline(s):
            return
        try:
            self._compute_layers(s)
            d = self._decide(s, None)
        except Exception as exc:  # scoring failed -> visible fail-open state, never a 500 and never a silent Clear
            self._fail_open(s, f"scoring_error: {type(exc).__name__}: {exc}")
            return
        self._apply(s, d, event="band_decided")

    def _account_capped(self, customer_id: str) -> bool:
        cc = self.cfg.challenge
        cutoff = self.clock() - cc.account_window_seconds
        with self._attempts_lock:
            recent = [t for t in self._failed_attempts.get(customer_id, []) if t > cutoff]
            if recent:
                self._failed_attempts[customer_id] = recent
            else:
                self._failed_attempts.pop(customer_id, None)
            return len(recent) >= cc.max_failed_attempts_per_account

    def _apply(self, s: Session, d: policy.Decision, event: str) -> None:
        if d.band is Band.STEP_UP and d.needs_challenge and self._account_capped(s.customer_id):
            # Too many failed digit answers on this account recently: do not hand out more
            # guesses. Pause for app confirmation and analyst review (Hold), never block.
            d = policy.Decision(Band.HOLD, d.strengths, d.reasons + ["l3_account_attempt_cap"],
                                needs_app_prompt=True)
        s.band, s.reasons = d.band, d.reasons
        s.decided_at = s.decided_at or self.clock()
        if d.band is Band.HOLD:
            s.status = "held"
            s.app = {"prompt_sent_at": iso(self.clock()), "result": None, "responded_at": None,
                     "confirmed": False}
            self._act(s, "app_prompt_sent")
            self._act(s, "case_opened_for_analyst")
            try:
                cust_hmac = hashlib.sha256((s.customer_id + "salt").encode("utf-8")).hexdigest()[:16]
                self.cases.create_case(
                    call_id=s.call_id,
                    customer_id_hmac=cust_hmac,
                    signals_summary={"reasons": s.reasons, "layers": {k: v.model_dump(mode="json") for k, v in s.layers.items()}}
                )
                self.alerts.emit_alert("HOLD_DECISION", s.call_id, {"reasons": s.reasons, "customer_id_hmac": cust_hmac})
            except Exception:
                pass
        elif d.band is Band.STEP_UP:
            s.status = "challenge_pending"
            s.challenge = chal.new_challenge(self.cfg.challenge, self.clock())
            self._act(s, "challenge_issued", digits=len(s.challenge.digits))
        else:
            s.status = "clear"
        self._act(s, f"band_{d.band.value.lower().replace(' ', '_')}")
        self._log(s, event)
        self._publish(s)

    # ------------------------------------------------------------- L3 and L5
    def answer_challenge(self, call_id: str, text: Optional[str] = None,
                         pcm: Optional[bytes] = None, sample_rate: int = 16000) -> CallView:
        s = self._get(call_id)
        with s.lock:
            if s.status != "challenge_pending" or s.challenge is None:
                raise Conflict("no digit challenge is pending for this call")
            received = self.clock()
            if text is None:
                try:
                    assert pcm is not None
                    text = self.asr.transcribe(audio.to_16k(pcm, sample_rate), audio.TARGET_RATE, s.metadata)
                except Exception as exc:
                    self._fail_open(s, f"model_error: ASR {type(exc).__name__}: {exc}", allow_step_up=False)
                    return self.view_of(s)
            res = chal.evaluate(s.challenge, text, received, self.cfg.challenge)
            s.l3 = {"outcome": res.outcome.value, "reason": res.reason,
                    "reply_seconds": round(res.reply_seconds, 3), "digits_heard": res.parsed_count,
                    "issued_at": iso(s.challenge.issued_at)}
            self._act(s, "challenge_answered", outcome=res.outcome.value)
            if res.outcome is not L3Outcome.PASS:
                with self._attempts_lock:
                    self._failed_attempts.setdefault(s.customer_id, []).append(received)
            if res.outcome is L3Outcome.PASS:
                s.status = "challenge_passed"
                l2 = s.layers.get("l2")
                if l2 is not None and l2.strength is Strength.STRONG:
                    # A live voice changer can pass digits. The agent carries on; analysts review after the call.
                    s.review = {"reason": "l2_strong_after_pass", "status": "open", "at": iso(self.clock())}
                    self._act(s, "flagged_for_post_call_review", reason="l2_strong_after_pass")
                elif s.request_type.value in set(self.cfg.sensitive_request_types):
                    # Review rule: sensitive request that passed Step up goes to next-day review queue
                    s.review = {"reason": "sensitive_request_step_up_passed", "status": "open", "at": iso(self.clock())}
                    self._act(s, "flagged_for_post_call_review", reason="sensitive_request_step_up_passed")
                self._log(s, "challenge_result")
                self._publish(s)
            else:
                d = self._decide(s, res.outcome)
                self._apply(s, d, event="challenge_result")
            return self.view_of(s)

    def app_response(self, call_id: str, result: AppResult) -> CallView:
        s = self._get(call_id)
        with s.lock:
            if not s.app or s.app.get("result") is not None:
                raise Conflict("no app prompt is awaiting a response")
            s.app["result"], s.app["responded_at"] = result.value, iso(self.clock())
            s.app["confirmed"] = result is AppResult.APPROVE  # deny and timeout both mean not confirmed
            self._act(s, "app_response", result=result.value)
            self._log(s, "app_response")
            self._publish(s)
            return self.view_of(s)

    # ----------------------------------------------------------- analyst work
    def _analyst_action(self, call_id: str, who: Principal, decision: str, note: str) -> CallView:
        authorize(who, Role.ANALYST)
        s = self._get(call_id)
        with s.lock:
            if s.band is not Band.HOLD or s.status != "held":
                raise Conflict("this call is not a held case")
            s.analyst = {"user": who.user, "decision": decision, "note": note, "at": iso(self.clock())}
            s.status = decision
            self._act(s, f"analyst_{decision}", user=who.user)
            self._log(s, f"analyst_{decision}")
            self._publish(s)
            return self.view_of(s)

    def release(self, call_id: str, who: Principal, note: str = "") -> CallView:
        return self._analyst_action(call_id, who, "released", note)

    def escalate(self, call_id: str, who: Principal, note: str = "") -> CallView:
        return self._analyst_action(call_id, who, "escalated", note)

    # --------------------------------------------------------- threshold admin
    def apply_thresholds(self, layer: str, weak: float, strong: float) -> None:
        if layer not in self.thresholds:
            raise ValueError(f"unknown layer {layer}")
        new = dict(self.thresholds)
        new[layer] = policy.Thresholds(weak, strong)
        self.thresholds = new  # atomic swap; applies to calls decided from now on
