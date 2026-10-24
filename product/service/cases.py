"""
Case store and lifecycle management for fraud analysts.
Provides full case audit trail: open, assign, note, and close actions.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import json
import os

CASES_DIR = Path("data/cases")


class CaseNote(BaseModel):
    author: str
    text: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FraudCase(BaseModel):
    case_id: str
    call_id: str
    customer_id_hmac: str
    status: str = "HELD"  # HELD, ANALYSIS, RESOLVED, CLOSED
    assigned_to: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signals_summary: Dict[str, Any] = Field(default_factory=dict)
    notes: List[CaseNote] = Field(default_factory=list)
    resolution: Optional[str] = None  # CONFIRM_FRAUD, DISMISS
    resolution_reason: Optional[str] = None


class CaseStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or CASES_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, case_id: str) -> Path:
        return self.base_dir / f"{case_id}.json"

    def create_case(
        self,
        call_id: str,
        customer_id_hmac: str,
        signals_summary: Optional[Dict[str, Any]] = None,
    ) -> FraudCase:
        case_id = f"case_{call_id}"
        case = FraudCase(
            case_id=case_id,
            call_id=call_id,
            customer_id_hmac=customer_id_hmac,
            signals_summary=signals_summary or {},
        )
        self.save(case)
        return case

    def save(self, case: FraudCase) -> None:
        case.updated_at = datetime.now(timezone.utc).isoformat()
        p = self._path(case.case_id)
        p.write_text(case.model_dump_json(indent=2), encoding="utf-8")

    def get(self, case_id: str) -> Optional[FraudCase]:
        p = self._path(case_id)
        if not p.exists():
            return None
        try:
            return FraudCase.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list_cases(self, status: Optional[str] = None) -> List[FraudCase]:
        cases = []
        for p in self.base_dir.glob("case_*.json"):
            try:
                c = FraudCase.model_validate_json(p.read_text(encoding="utf-8"))
                if status is None or c.status == status:
                    cases.append(c)
            except Exception:
                continue
        cases.sort(key=lambda x: x.created_at, reverse=True)
        return cases

    def assign(self, case_id: str, analyst_id: str) -> Optional[FraudCase]:
        case = self.get(case_id)
        if not case:
            return None
        case.assigned_to = analyst_id
        case.status = "ANALYSIS"
        self.save(case)
        return case

    def add_note(self, case_id: str, author: str, note_text: str) -> Optional[FraudCase]:
        case = self.get(case_id)
        if not case:
            return None
        case.notes.append(CaseNote(author=author, text=note_text))
        self.save(case)
        return case

    def resolve(self, case_id: str, resolution: str, reason: str) -> Optional[FraudCase]:
        case = self.get(case_id)
        if not case:
            return None
        case.resolution = resolution
        case.resolution_reason = reason
        case.status = "RESOLVED"
        self.save(case)
        return case
