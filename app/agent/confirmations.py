"""
Server-side employee confirmation (BR06, first half).

The agent may PROPOSE an action. Only the employee's own chat turn can CONFIRM it, and that is recorded
here, outside the planner. A write tool then refuses to run unless it finds a confirmation that is
confirmed, belongs to that employee, names that action, matches the exact parameters, and is unused.
So a planner (or a model) that "decides" to create a ticket without the employee saying yes is blocked
at the tool, not merely discouraged.
"""

from __future__ import annotations

import hashlib
import json
from itertools import count


def fingerprint(obj) -> str:
    """Stable SHA-256 of a JSON-compatible object (key order does not matter)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


class ConfirmationError(Exception):
    """`code` is what a CALLER may see. `internal` is the precise reason, for the approver-only audit log.

    Someone else's confirmation and a confirmation that does not exist both carry the code `unknown_confirmation`, so a
    caller cannot tell them apart. Confirmation IDs are sequential (CONF-0001 ...), so this stops them being probed."""

    def __init__(self, code: str, message: str = "", internal: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.internal = internal or code


PROPOSED, CONFIRMED, CONSUMED, CANCELLED = "PROPOSED", "CONFIRMED", "CONSUMED", "CANCELLED"


class ConfirmationStore:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self._ids = count(1)

    def propose(self, employee_id: str, session_id: str, action: str, params: dict) -> str:
        confirmation_id = f"CONF-{next(self._ids):04d}"
        self._records[confirmation_id] = {
            "confirmation_id": confirmation_id, "employee_id": employee_id, "session_id": session_id,
            "action": action, "params_hash": fingerprint(params), "status": PROPOSED,
        }
        return confirmation_id

    def confirm(self, employee_id: str, session_id: str, confirmation_id: str) -> None:
        """Record the employee's yes. Safe to repeat for an already-confirmed (not yet used) proposal."""
        record = self._records.get(confirmation_id)
        if record is None:
            raise ConfirmationError("unknown_confirmation")
        if record["employee_id"] != employee_id or record["session_id"] != session_id:
            raise ConfirmationError("unknown_confirmation", internal="wrong_employee")  # looks exactly like a missing ID
        if record["status"] == CONFIRMED:
            return
        if record["status"] != PROPOSED:
            raise ConfirmationError("already_used" if record["status"] == CONSUMED else "cancelled")
        record["status"] = CONFIRMED

    def cancel(self, confirmation_id: str) -> None:
        record = self._records.get(confirmation_id)
        if record is not None and record["status"] in (PROPOSED, CONFIRMED):
            record["status"] = CANCELLED

    def validate(self, employee_id: str, action: str, params: dict, confirmation_id) -> dict:
        record = self._records.get(confirmation_id) if isinstance(confirmation_id, str) else None
        if record is None:
            raise ConfirmationError("unknown_confirmation")
        if record["employee_id"] != employee_id:
            raise ConfirmationError("unknown_confirmation", internal="wrong_employee")  # looks exactly like a missing ID
        if record["status"] == CONSUMED:
            raise ConfirmationError("already_used")
        if record["status"] == CANCELLED:
            raise ConfirmationError("cancelled")
        if record["status"] != CONFIRMED:
            raise ConfirmationError("not_confirmed")
        if record["action"] != action:
            raise ConfirmationError("action_mismatch")
        if record["params_hash"] != fingerprint(params):
            raise ConfirmationError("params_changed")
        return dict(record)

    def consume(self, confirmation_id: str) -> None:
        self._records[confirmation_id]["status"] = CONSUMED

    def get(self, confirmation_id: str):
        record = self._records.get(confirmation_id)
        return dict(record) if record else None
