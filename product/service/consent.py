"""
Consent verification and management for Asli Awaaz.
Enforces the strict consent gate: no voice recording, training, or synthetic cloning
may occur unless an explicit, signed consent record exists on disk.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
import os
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ConsentRecord(BaseModel):
    speaker_id: str
    full_name: str
    signed: bool = False
    signed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    allow_recording: bool = True
    allow_spoof_testing: bool = True
    allow_voice_cloning: bool = True
    retention_days: int = 90
    metadata: Dict[str, Any] = Field(default_factory=dict)


CONSENT_DIR = Path("data/consent")


def get_consent_path(speaker_id: str, consent_dir: Optional[Path] = None) -> Path:
    d = consent_dir or CONSENT_DIR
    return d / f"{speaker_id}.json"


def save_consent(record: ConsentRecord, consent_dir: Optional[Path] = None) -> Path:
    d = consent_dir or CONSENT_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = get_consent_path(record.speaker_id, d)
    p.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return p


def get_consent(speaker_id: str, consent_dir: Optional[Path] = None) -> Optional[ConsentRecord]:
    p = get_consent_path(speaker_id, consent_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ConsentRecord.model_validate(data)
    except Exception:
        return None


def verify_consent_for_cloning(speaker_id: str, consent_dir: Optional[Path] = None) -> bool:
    """Strict consent gate: returns True only if valid signed consent covers voice cloning."""
    record = get_consent(speaker_id, consent_dir)
    if not record:
        return False
    return bool(record.signed and record.allow_voice_cloning and record.allow_recording)


def assert_consent_for_cloning(speaker_id: str, consent_dir: Optional[Path] = None) -> None:
    """Raises PermissionError if consent gate fails. Cannot be bypassed."""
    if not verify_consent_for_cloning(speaker_id, consent_dir):
        raise PermissionError(
            f"Consent gate violation: Speaker '{speaker_id}' does not have a verified, "
            f"signed consent record permitting voice cloning in {consent_dir or CONSENT_DIR}."
        )
