"""L4 context rules and the band policy.

A signal is strong when its calibrated probability is >= its upper threshold
and weak when >= its lower threshold. Policy:

  Hold      two strong signals, or L3 failed/unclear, or (not enrolled and the
            request is sensitive: goes straight to app confirmation).
  Step up   one strong signal, or two weak signals, or a sensitive request.
  Clear     otherwise.

One weak signal never produces Hold. L3 and L5 are not scored signals; they
only run after Step up / Hold respectively.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .config import ContextConfig
from .models import BankFlags, Band, L3Outcome, Strength


@dataclass(frozen=True)
class Thresholds:
    weak: float
    strong: float

    def __post_init__(self):
        if not 0.0 < self.weak < self.strong < 1.0:
            raise ValueError("need 0 < weak < strong < 1")


def classify(prob: float, thr: Thresholds) -> Strength:
    if prob >= thr.strong:
        return Strength.STRONG
    if prob >= thr.weak:
        return Strength.WEAK
    return Strength.NONE


# ------------------------------------------------------------------ L4
def _term_regex(term: str) -> "re.Pattern[str]":
    t = re.escape(unicodedata.normalize("NFC", term).casefold()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){t}(?!\w)")


def urgency_hits(text: str, cfg: ContextConfig) -> List[str]:
    """Distinct urgency terms present in text (English, Hinglish, Devanagari)."""
    norm = unicodedata.normalize("NFC", text).casefold()
    return [t for t in cfg.urgency_terms if _term_regex(t).search(norm)]


def context_raw_score(flags: BankFlags, transcript: str, cfg: ContextConfig) -> Tuple[float, List[str]]:
    """Raw L4 score: bank-flag weights plus capped urgency-term weights."""
    raw = sum(cfg.flag_weights.get(name, 0.0) for name, on in flags.model_dump().items() if on)
    hits = urgency_hits(transcript, cfg)
    raw += min(sum(cfg.urgency_terms[t] for t in hits), cfg.urgency_cap)
    return raw, hits


# -------------------------------------------------------------- decision
@dataclass
class Decision:
    band: Band
    strengths: Dict[str, Strength]
    reasons: List[str] = field(default_factory=list)  # internal only, never shown to agents
    needs_challenge: bool = False
    needs_app_prompt: bool = False


def decide(
    request_type: str,
    enrolled: bool,
    probs: Mapping[str, Optional[float]],
    thresholds: Mapping[str, Thresholds],
    sensitive_types: Iterable[str],
    l3: Optional[L3Outcome] = None,
) -> Decision:
    """Apply the band policy. probs maps layer -> calibrated probability (None = absent)."""
    active = ("l1", "l2", "l4") if enrolled else ("l2", "l4")
    strengths: Dict[str, Strength] = {}
    for layer in active:
        p = probs.get(layer)
        if p is not None:
            strengths[layer] = classify(p, thresholds[layer])
    strong = sum(1 for s in strengths.values() if s is Strength.STRONG)
    weak = sum(1 for s in strengths.values() if s is Strength.WEAK)
    sensitive = request_type in set(sensitive_types)

    reasons: List[str] = []
    if strong >= 2:
        reasons.append("two_strong_signals")
    if l3 in (L3Outcome.FAIL, L3Outcome.UNCLEAR):
        reasons.append(f"l3_{l3.value}")
    if not enrolled and sensitive:
        reasons.append("not_enrolled_sensitive_request")
    if reasons:
        return Decision(Band.HOLD, strengths, reasons, needs_app_prompt=True)

    if strong == 1:
        reasons.append("one_strong_signal")
    if weak >= 2:
        reasons.append("two_weak_signals")
    if sensitive:
        reasons.append("sensitive_request")
    if reasons:
        return Decision(Band.STEP_UP, strengths, reasons, needs_challenge=l3 is None)

    return Decision(Band.CLEAR, strengths, ["no_signal"])
