"""
Voiceprint enrolment store and embedding manager for L1 (Speaker Verification).
Manages customer voiceprints, ensuring enrolment requires active consent and
supports immediate, verifiable withdrawal (opt-out).
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import numpy as np
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from service.consent import get_consent

ENROLMENT_DIR = Path("data/enrolments")


class VoiceprintRecord(BaseModel):
    customer_id: str
    enrolled_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_version: str = "speechbrain-ecapa-tdnn-v1"
    embedding_dim: int = 192
    embedding: List[float]
    sample_count: int = 3
    withdrawn: bool = False
    withdrawn_at: Optional[str] = None


class EnrolmentStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or ENROLMENT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, customer_id: str) -> Path:
        return self.base_dir / f"{customer_id}.json"

    def enrol(
        self,
        customer_id: str,
        embedding: np.ndarray,
        model_version: str = "speechbrain-ecapa-tdnn-v1",
        sample_count: int = 3,
        enforce_consent: bool = True,
    ) -> VoiceprintRecord:
        """Enrol a customer voiceprint. Rejects if consent is required and missing."""
        if enforce_consent:
            consent = get_consent(customer_id)
            if not consent or not consent.signed or not consent.allow_recording:
                raise PermissionError(
                    f"Enrolment rejected: Customer '{customer_id}' has not given signed consent."
                )

        vec = embedding.flatten().tolist()
        record = VoiceprintRecord(
            customer_id=customer_id,
            model_version=model_version,
            embedding_dim=len(vec),
            embedding=vec,
            sample_count=sample_count,
        )
        p = self._path(customer_id)
        p.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return record

    def get_embedding(self, customer_id: str) -> Optional[np.ndarray]:
        p = self._path(customer_id)
        if not p.exists():
            return None
        try:
            rec = VoiceprintRecord.model_validate_json(p.read_text(encoding="utf-8"))
            if rec.withdrawn:
                return None
            return np.array(rec.embedding, dtype=np.float32)
        except Exception:
            return None

    def withdraw(self, customer_id: str) -> bool:
        """Immediate, verifiable withdrawal of biometric voiceprint."""
        p = self._path(customer_id)
        if not p.exists():
            return False
        rec = VoiceprintRecord.model_validate_json(p.read_text(encoding="utf-8"))
        rec.withdrawn = True
        rec.withdrawn_at = datetime.now(timezone.utc).isoformat()
        rec.embedding = []  # Wipe the biometric embedding immediately
        p.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
        return True

    def delete(self, customer_id: str) -> bool:
        """Physical deletion of record from disk."""
        p = self._path(customer_id)
        if p.exists():
            p.unlink()
            return True
        return False
