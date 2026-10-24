"""L3 digit challenge: generation, answer normalisation, reply-time check."""
from __future__ import annotations

import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

from .config import ChallengeConfig
from .models import L3Outcome

# --- digit words ---------------------------------------------------------
_ROMAN = {
    "0": ["zero", "shunya", "shoonya", "sunya"],
    "1": ["one", "ek", "ik"],
    "2": ["two", "do"],
    "3": ["three", "teen", "tin"],
    "4": ["four", "char", "chaar", "chār"],
    "5": ["five", "paanch", "panch", "paach", "pach"],
    "6": ["six", "chhah", "chhe", "chhey", "chheh", "chhai", "chah", "che"],
    "7": ["seven", "saat", "sat"],
    "8": ["eight", "aath", "ath", "aatth"],
    "9": ["nine", "nau", "nao"],
}
_DEVANAGARI = {
    "0": ["शून्य", "ज़ीरो", "जीरो"],
    "1": ["एक", "वन"],
    "2": ["दो", "टू"],
    "3": ["तीन", "थ्री"],
    "4": ["चार", "फोर"],
    "5": ["पांच", "पाँच", "पाच", "फाइव"],
    "6": ["छह", "छः", "छे", "छ", "सिक्स"],
    "7": ["सात", "सेवन"],
    "8": ["आठ", "एट"],
    "9": ["नौ", "नव", "नाइन"],
}
WORD_TO_DIGIT = {
    unicodedata.normalize("NFC", w).casefold(): d
    for table in (_ROMAN, _DEVANAGARI)
    for d, words in table.items()
    for w in words
}
_REPEAT = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3}
_SPLIT = re.compile(r"[^\wऀ-ॿ]+")


def normalise_digits(text: str) -> List[str]:
    """Extract the digits spoken or written in text, in order.

    Handles ASCII and Devanagari numerals, English digit words, romanised and
    Devanagari Hindi digit words, and 'double'/'triple' (double teen -> 33).
    Everything else is treated as filler and skipped. Known ambiguity: 'do'
    (two) is also an English word, so 'please do repeat' adds a stray 2; the
    count check in evaluate() then yields 'unclear' rather than a pass.
    """
    out: List[str] = []
    repeat = 1
    for tok in _SPLIT.split(unicodedata.normalize("NFC", text).casefold()):
        if not tok:
            continue
        if tok in _REPEAT:
            repeat = _REPEAT[tok]
            continue
        if all(ch.isdecimal() for ch in tok):
            out.extend(str(unicodedata.decimal(ch)) for ch in tok)
            repeat = 1
        elif tok in WORD_TO_DIGIT:
            out.extend([WORD_TO_DIGIT[tok]] * repeat)
            repeat = 1
        else:
            repeat = 1
    return out


# --- challenge -----------------------------------------------------------
def generate_digits(n: int = 6) -> str:
    """n random decimal digits from the OS CSPRNG (repeats allowed)."""
    return "".join(secrets.choice("0123456789") for _ in range(n))


def format_for_agent(digits: str) -> str:
    return " ".join(digits)


@dataclass
class Challenge:
    digits: str
    issued_at: float


@dataclass
class ChallengeResult:
    outcome: L3Outcome
    reason: str
    reply_seconds: float
    parsed_count: int


def new_challenge(cfg: ChallengeConfig, now: float, digits: Optional[str] = None) -> Challenge:
    return Challenge(digits=digits or generate_digits(cfg.digits), issued_at=now)


def evaluate(ch: Challenge, answer_text: str, now: float, cfg: ChallengeConfig) -> ChallengeResult:
    """Score an answer.

    unclear: no digits, or a different number of digits than were asked.
    fail:    right count but wrong digits, or reply outside the time window.
    pass:    digits match and the reply time is inside [min, max].
    """
    reply = now - ch.issued_at
    parsed = normalise_digits(answer_text or "")
    n = len(parsed)
    if n != len(ch.digits):
        return ChallengeResult(L3Outcome.UNCLEAR, "digit_count_mismatch", reply, n)
    if not hmac.compare_digest("".join(parsed), ch.digits):
        return ChallengeResult(L3Outcome.FAIL, "digits_mismatch", reply, n)
    if reply > cfg.max_reply_seconds:
        return ChallengeResult(L3Outcome.FAIL, "reply_too_slow", reply, n)
    if reply < cfg.min_reply_seconds:
        return ChallengeResult(L3Outcome.FAIL, "reply_too_fast", reply, n)
    return ChallengeResult(L3Outcome.PASS, "ok", reply, n)
