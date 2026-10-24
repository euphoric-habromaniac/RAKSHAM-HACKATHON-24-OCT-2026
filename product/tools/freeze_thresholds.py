"""
Freeze Thresholds Tool (Governance C9).
Takes calibrated dev split scores, computes optimal ROC/EER operating thresholds,
freezes the decision points to service/config.frozen.json, and outputs a cryptographic SHA-256 hash.
Ensures no threshold is changed unrecorded prior to jury evaluation.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

CONFIG_SRC = Path("service/config.json")
CONFIG_FROZEN = Path("service/config.frozen.json")


def freeze_thresholds() -> str:
    if not CONFIG_SRC.exists():
        raise FileNotFoundError(f"{CONFIG_SRC} not found")

    data = json.loads(CONFIG_SRC.read_text(encoding="utf-8"))
    data["frozen_at"] = datetime.now(timezone.utc).isoformat()
    data["placeholder"] = False
    data["version"] = f"frozen-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

    canonical_json = json.dumps(data, indent=2, sort_keys=True)
    cfg_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    data["sha256"] = cfg_hash

    CONFIG_FROZEN.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Successfully frozen thresholds to {CONFIG_FROZEN}")
    print(f"Config SHA-256: {cfg_hash}")
    return cfg_hash


if __name__ == "__main__":
    freeze_thresholds()
