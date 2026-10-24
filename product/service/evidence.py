"""Append-only, SHA-256 hash-chained evidence log (JSON lines).

Each line is {"seq", "ts", "call_id", "event", "data", "prev_hash", "hash"}.
hash = SHA-256 over the canonical JSON of every field except "hash", and
prev_hash is the previous record's hash (64 zeros for the first record). An
edit, insertion, reordering or deletion in the middle of the file breaks the
chain. Deleting records from the END cannot be detected from the file alone:
anchor head_hash() somewhere else (a separate system or a printed receipt).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

GENESIS_HASH = "0" * 64


class EvidenceError(RuntimeError):
    pass


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_hash(record: Dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class VerifyResult:
    ok: bool
    records: int
    head_hash: str
    bad_seq: Optional[int] = None
    reason: Optional[str] = None


def _read_lines(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield line


def verify_chain(path: Union[str, Path]) -> VerifyResult:
    """Re-compute every hash and link in the file. A missing file is an empty, valid chain."""
    p = Path(path)
    prev = GENESIS_HASH
    count = 0
    if not p.exists():
        return VerifyResult(True, 0, prev)
    for i, line in enumerate(_read_lines(p)):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return VerifyResult(False, count, prev, i, "unparseable record")
        if not isinstance(rec, dict) or rec.get("seq") != i:
            return VerifyResult(False, count, prev, i, "sequence number mismatch")
        if rec.get("prev_hash") != prev:
            return VerifyResult(False, count, prev, i, "prev_hash does not match previous record")
        if rec.get("hash") != compute_hash(rec):
            return VerifyResult(False, count, prev, i, "record hash mismatch (content altered)")
        prev = rec["hash"]
        count += 1
    return VerifyResult(True, count, prev)


class EvidenceLog:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._seq = 0
        self._head = GENESIS_HASH
        if self.path.exists():
            last = None
            for last in _read_lines(self.path):
                pass
            if last is not None:
                try:
                    rec = json.loads(last)
                    self._seq, self._head = rec["seq"] + 1, rec["hash"]
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise EvidenceError("existing evidence log is unreadable; run verify_chain") from exc

    def head_hash(self) -> str:
        return self._head

    def append(self, call_id: Optional[str], event: str, data: Dict[str, Any], ts: float) -> Dict[str, Any]:
        with self._lock:
            rec: Dict[str, Any] = {
                "seq": self._seq,
                "ts": iso(ts),
                "call_id": call_id,
                "event": event,
                "data": data,
                "prev_hash": self._head,
            }
            rec["hash"] = compute_hash(rec)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._seq += 1
            self._head = rec["hash"]
            return rec

    def records(self, call_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        recs = [json.loads(line) for line in _read_lines(self.path)]
        return [r for r in recs if call_id is None or r["call_id"] == call_id]

    def verify(self) -> VerifyResult:
        return verify_chain(self.path)
