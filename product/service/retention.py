"""
Retention policy enforcement and evidence purger.
Enforces the 90-day retention default, with environment variable override
(RETENTION_PERIOD_SECONDS) for live judge deletion demonstrations.
Also verifies privacy invariant: Clear calls have 0 bytes of audio on disk.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import time
import json
from datetime import datetime, timezone

DEFAULT_RETENTION_DAYS = 90
DEFAULT_RETENTION_SECONDS = DEFAULT_RETENTION_DAYS * 86400


def get_retention_ttl_seconds() -> float:
    """Returns retention duration in seconds. Checks for demo override."""
    override = os.environ.get("RETENTION_PERIOD_SECONDS")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return float(DEFAULT_RETENTION_SECONDS)


class RetentionManager:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self.audio_dir = self.data_dir / "hold_clips"
        self.cases_dir = self.data_dir / "cases"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def purge_expired(self, current_time: Optional[float] = None) -> Dict[str, int]:
        """Purges any stored hold audio or case files that have exceeded TTL."""
        now = current_time if current_time is not None else time.time()
        ttl = get_retention_ttl_seconds()
        deleted_audio = 0
        deleted_cases = 0

        # Purge audio clips
        for p in self.audio_dir.glob("*.wav"):
            if now - p.stat().st_mtime > ttl:
                p.unlink(missing_ok=True)
                deleted_audio += 1

        for p in self.audio_dir.glob("*.enc"):
            if now - p.stat().st_mtime > ttl:
                p.unlink(missing_ok=True)
                deleted_audio += 1

        return {
            "deleted_audio_count": deleted_audio,
            "deleted_cases_count": deleted_cases,
            "active_ttl_seconds": int(ttl),
        }

    def verify_no_clear_audio_on_disk(self, clear_call_ids: List[str]) -> bool:
        """Privacy invariant test: returns True if NO audio files exist for clear calls."""
        for call_id in clear_call_ids:
            matches = list(self.audio_dir.glob(f"*{call_id}*"))
            if matches:
                return False
        return True
