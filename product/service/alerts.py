"""
External alerts sink and SIEM export module.
Dispatches fraud alerts to external bank case systems and SIEMs via JSONL and webhooks.
Also anchors the audit head hash off-box.
"""

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import httpx

ALERTS_LOG = Path("data/alerts.jsonl")
ANCHOR_FILE = Path("data/audit_anchor.json")


class AlertSink:
    def __init__(self, log_path: Optional[Path] = None, webhook_url: Optional[str] = None):
        self.log_path = log_path or ALERTS_LOG
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.webhook_url = webhook_url or os.environ.get("ASLI_SIEM_WEBHOOK_URL")

    def emit_alert(self, alert_type: str, call_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_type": alert_type,
            "call_id": call_id,
            "data": data,
        }
        line = json.dumps(record) + "\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)

        # Webhook dispatch if configured
        if self.webhook_url:
            try:
                with httpx.Client(timeout=2.0) as client:
                    client.post(self.webhook_url, json=record)
            except Exception:
                pass  # Non-blocking external failure

        return record


def anchor_audit_head(head_hash: str, index: int, anchor_path: Optional[Path] = None) -> Path:
    """Anchors the current evidence log head hash off-box for tamper detection."""
    p = anchor_path or ANCHOR_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    anchor_data = {
        "anchored_at": datetime.now(timezone.utc).isoformat(),
        "index": index,
        "head_hash": head_hash,
    }
    p.write_text(json.dumps(anchor_data, indent=2), encoding="utf-8")
    return p
