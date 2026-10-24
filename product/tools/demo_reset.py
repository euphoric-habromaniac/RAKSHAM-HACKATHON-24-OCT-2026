"""
Demo Reset Tool (make demo-reset).
Purges temporary state, reinitializes clean SQLite/JSONL evidence logs,
and pre-seeds demo identities and consent records for the 3 demo scenarios.
"""

from pathlib import Path
import shutil
import json
import time
from datetime import datetime, timezone
from service.consent import ConsentRecord, save_consent
from service.enrol import EnrolmentStore
import numpy as np

DATA_DIR = Path("data")


def reset_demo() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    # 1. Reset hold clips
    clips_dir = DATA_DIR / "hold_clips"
    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 2. Reset cases
    cases_dir = DATA_DIR / "cases"
    if cases_dir.exists():
        shutil.rmtree(cases_dir)
    cases_dir.mkdir(parents=True, exist_ok=True)

    # 3. Reset alerts
    alerts_file = DATA_DIR / "alerts.jsonl"
    alerts_file.write_text("", encoding="utf-8")

    # 4. Reset evidence log
    evidence_file = DATA_DIR / "evidence.jsonl"
    evidence_file.write_text("", encoding="utf-8")

    # 5. Pre-seed demo consented personas
    consent_dir = DATA_DIR / "consent"
    consent_dir.mkdir(parents=True, exist_ok=True)

    c1 = ConsentRecord(
        speaker_id="cust_genuine",
        full_name="Rajesh Sharma (Consented Demo Customer)",
        signed=True,
        allow_recording=True,
        allow_spoof_testing=True,
        allow_voice_cloning=True,
    )
    save_consent(c1)

    c2 = ConsentRecord(
        speaker_id="cust_victim",
        full_name="Kushagra Raj (Victim Voice Clone Target)",
        signed=True,
        allow_recording=True,
        allow_spoof_testing=True,
        allow_voice_cloning=True,
    )
    save_consent(c2)

    # 6. Pre-enrol voiceprints
    enrol_store = EnrolmentStore()
    dummy_vec = np.zeros(192, dtype=np.float32)
    dummy_vec[0] = 0.8
    enrol_store.enrol("cust_genuine", dummy_vec, enforce_consent=True)
    enrol_store.enrol("cust_victim", dummy_vec, enforce_consent=True)

    print("Demo state successfully reset to clean baseline.")
    print("Pre-seeded personas: 'cust_genuine' and 'cust_victim' (both consented and enrolled).")


if __name__ == "__main__":
    reset_demo()
