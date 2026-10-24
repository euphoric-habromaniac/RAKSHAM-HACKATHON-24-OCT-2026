"""Service configuration: Platt parameters, thresholds, word lists.

Loaded from JSON, or YAML when PyYAML is installed. The shipped config.json is
all placeholders and says so; a warning is logged whenever placeholders are
loaded.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Union

from pydantic import BaseModel, Field, model_validator

log = logging.getLogger("asli.config")

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")


class PlattParams(BaseModel):
    a: float
    b: float


class LayerConfig(BaseModel):
    placeholder: bool = True  # False once platt/thresholds are fitted on data
    platt: PlattParams
    weak: float = Field(gt=0.0, lt=1.0)
    strong: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "LayerConfig":
        if self.weak >= self.strong:
            raise ValueError("weak threshold must be below strong threshold")
        return self


class ChallengeConfig(BaseModel):
    digits: int = Field(default=6, ge=4, le=10)
    min_reply_seconds: float = Field(default=1.0, ge=0.0)
    max_reply_seconds: float = Field(default=15.0, gt=0.0)
    # Per-call cap is one attempt (see engine.answer_challenge). Per-account cap: once a
    # customer has this many failed or unclear answers inside the window, further Step ups
    # for that customer go to Hold (app confirmation + analyst) instead of issuing digits.
    max_failed_attempts_per_account: int = Field(default=3, ge=1)
    account_window_seconds: float = Field(default=3600.0, gt=0.0)


class ContextConfig(BaseModel):
    flag_weights: Dict[str, float]
    urgency_cap: float = 2.0
    urgency_terms: Dict[str, float]


class ServiceConfig(BaseModel):
    placeholder: bool = True
    version: str
    deadline_seconds: float = Field(default=10.0, gt=0.0)
    sensitive_request_types: List[str]
    layers: Dict[str, LayerConfig]
    challenge: ChallengeConfig = Field(default_factory=ChallengeConfig)
    l4: ContextConfig

    @model_validator(mode="after")
    def _layers_present(self) -> "ServiceConfig":
        missing = {"l1", "l2", "l4"} - set(self.layers)
        if missing:
            raise ValueError(f"missing layer config: {sorted(missing)}")
        return self


def load_config(path: Union[str, Path, None] = None) -> ServiceConfig:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("YAML config needs PyYAML; use JSON or pip install pyyaml") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    cfg = ServiceConfig.model_validate(data)
    if cfg.placeholder:
        log.warning(
            "Loaded PLACEHOLDER calibration/thresholds from %s (version %s). "
            "These values are not fitted on data.", p, cfg.version,
        )
    return cfg
