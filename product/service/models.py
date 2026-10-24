"""Pydantic schemas shared by the engine and the HTTP API."""
from __future__ import annotations

import base64
import binascii
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_AUDIO_B64_CHARS = 2_800_000  # about 2 MB of PCM per chunk


class Band(str, Enum):
    CLEAR = "Clear"
    STEP_UP = "Step up"
    HOLD = "Hold"
    UNAVAILABLE = "Unavailable"


class Strength(str, Enum):
    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"


class RequestType(str, Enum):
    BALANCE = "balance"
    LIMIT_CHANGE = "limit_change"
    NEW_PAYEE = "new_payee"
    MOBILE_CHANGE = "mobile_change"
    DEVICE_CHANGE = "device_change"
    OTHER = "other"


class L3Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCLEAR = "unclear"


class AppResult(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    TIMEOUT = "timeout"


class BankFlags(BaseModel):
    new_device: bool = False
    new_payee: bool = False
    amount_jump: bool = False


class StartCallRequest(BaseModel):
    call_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=128)
    request_type: RequestType
    enrolled: bool
    bank_flags: BankFlags = Field(default_factory=BankFlags)
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Read only by the mock scorers (mock_l1_cosine, mock_l2_spoof, mock_error, ...).",
    )


def _decode_pcm_b64(value: str) -> bytes:
    if len(value) > MAX_AUDIO_B64_CHARS:
        raise ValueError("audio chunk too large")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("pcm_b64 is not valid base64") from exc
    if not raw:
        raise ValueError("audio chunk is empty")
    if len(raw) % 2:
        raise ValueError("PCM must be 16-bit samples (even byte count)")
    return raw


class AudioChunkIn(BaseModel):
    pcm_b64: str
    sample_rate: Literal[8000, 16000] = 16000

    @field_validator("pcm_b64")
    @classmethod
    def _check(cls, v: str) -> str:
        _decode_pcm_b64(v)
        return v

    def pcm(self) -> bytes:
        return _decode_pcm_b64(self.pcm_b64)


class TranscriptIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    final: bool = True


class ChallengeAnswerIn(BaseModel):
    """Either the speech-to-text answer, or raw audio for the ASR adapter."""

    text: Optional[str] = Field(default=None, max_length=1000)
    pcm_b64: Optional[str] = None
    sample_rate: Literal[8000, 16000] = 16000

    @model_validator(mode="after")
    def _one_of(self) -> "ChallengeAnswerIn":
        if (self.text is None) == (self.pcm_b64 is None):
            raise ValueError("send exactly one of text or pcm_b64")
        if self.pcm_b64 is not None:
            _decode_pcm_b64(self.pcm_b64)
        return self

    def pcm(self) -> bytes:
        assert self.pcm_b64 is not None
        return _decode_pcm_b64(self.pcm_b64)


class AppResponseIn(BaseModel):
    result: AppResult


class CaseActionIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class LayerScore(BaseModel):
    raw: float
    prob: float
    strength: Strength


class CallView(BaseModel):
    """What the agent desktop sees. Never contains a score or the layer that fired."""

    call_id: str
    status: str
    band: Optional[Band] = None
    agent_message: str
    challenge_pending: bool = False
    app_prompt_pending: bool = False
    # Per-call counter, bumped on every state change. A consumer keeps the highest
    # seq it has shown and ignores any message with seq <= that, so a late duplicate
    # can never overwrite a newer state.
    seq: int = 0


class ThresholdProposalIn(BaseModel):
    layer: Literal["l1", "l2", "l4"]
    weak: float = Field(gt=0.0, lt=1.0)
    strong: float = Field(gt=0.0, lt=1.0)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _ordered(self) -> "ThresholdProposalIn":
        if self.weak >= self.strong:
            raise ValueError("weak threshold must be below strong threshold")
        return self


class ThresholdProposalView(BaseModel):
    proposal_id: str
    layer: str
    weak: float
    strong: float
    reason: str
    proposed_by: str
    approvers: List[str]
    status: Literal["pending", "applied"]
