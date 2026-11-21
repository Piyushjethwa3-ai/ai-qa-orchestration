"""
The audit log (BR05, BR12): every attempted tool action leaves a REDACTED record, allowed or denied.

Records are redacted BEFORE they are stored or written, so a secret never reaches the log. Each record
carries the hash of the previous one, so removing or editing a record breaks the chain and
`verify_chain()` reports where. That makes tampering detectable. It does not make it impossible: someone
who can rewrite the whole file can recompute the chain, so a real system also needs write-once storage.

A `correlation_id` (the privileged request ID) links the request, the IT decision and the execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.governance.redaction import redact

GENESIS = "0" * 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(prev_hash: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256((prev_hash + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path | str | None = None, clock=_utc_now):
        self._records: list[dict] = []
        self._path = Path(path) if path else None
        self._clock = clock
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **fields) -> dict:
        seq = len(self._records) + 1
        prev = self._records[-1]["hash"] if self._records else GENESIS
        record = redact({"audit_id": f"AUD-{seq:06d}", "seq": seq, "timestamp": self._clock(), **fields})
        record["prev_hash"] = prev
        record["hash"] = _digest(prev, record)
        self._records.append(record)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        return copy.deepcopy(record)

    def records(self) -> list[dict]:
        return copy.deepcopy(self._records)

    def for_request(self, request_id: str) -> list[dict]:
        return [r for r in self.records() if r.get("request_id") == request_id]

    def for_correlation(self, correlation_id: str) -> list[dict]:
        return [r for r in self.records() if r.get("correlation_id") == correlation_id]

    def verify_chain(self, records: list[dict] | None = None) -> tuple[bool, int | None]:
        """(True, None) if intact, else (False, index of the first bad record)."""
        prev = GENESIS
        for index, record in enumerate(self._records if records is None else records):
            if record.get("prev_hash") != prev or record.get("hash") != _digest(prev, record):
                return False, index
            prev = record["hash"]
        return True, None

    def __len__(self) -> int:
        return len(self._records)
