"""
IT approvals for privileged actions (BR06 second half, BR07).

An approval is a record, created by the server and decided only by a known IT approver. It is bound to
ONE employee, ONE action, the EXACT parameters and ONE request ID. Execution re-checks all four and
refuses on any difference. An approval is single use. Rejected, pending, expired, mismatched and reused
approvals cannot execute. Text typed in chat ("my manager approved") is never an approval, because the
only way to approve is `decide()`, which needs an approver identity that the chat path cannot supply.
"""

from __future__ import annotations

import time
from itertools import count

from app import data
from app.agent.confirmations import fingerprint

PENDING, APPROVED, REJECTED, USED, EXPIRED = "PENDING", "APPROVED", "REJECTED", "USED", "EXPIRED"

# action -> the parameters it takes (and only these)
PRIVILEGED_ACTIONS = {
    "password_reset": ("target_employee_id",),
    "software_access_grant": ("target_employee_id", "application"),
}


class ApprovalError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def load_approvers() -> dict:
    return {a["approver_id"]: a for a in data.load_json_file("approvers.json")}


def validate_action(action, params) -> dict:
    """Return the clean parameter dict for a privileged action, or raise ApprovalError('invalid_request')."""
    if action not in PRIVILEGED_ACTIONS or not isinstance(params, dict):
        raise ApprovalError("invalid_request", "unknown privileged action")
    if set(params) != set(PRIVILEGED_ACTIONS[action]):
        raise ApprovalError("invalid_request", f"{action} takes exactly: {', '.join(PRIVILEGED_ACTIONS[action])}")
    for key, value in params.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 60:
            raise ApprovalError("invalid_request", f"invalid value for {key}")
    return dict(params)


class ApprovalService:
    def __init__(self, approvers: dict | None = None, clock=time.time, ttl_seconds: int = 900):
        self._approvers = approvers if approvers is not None else load_approvers()
        self._clock = clock
        self._ttl = ttl_seconds
        self._requests: dict[str, dict] = {}
        self._by_key: dict[tuple, str] = {}
        self._ids = count(1)

    @staticmethod
    def _binding(request_id: str, employee_id: str, action: str, params: dict) -> str:
        return fingerprint({"request_id": request_id, "employee_id": employee_id, "action": action, "params": params})

    def is_approver(self, approver_id: str) -> bool:
        return approver_id in self._approvers

    def create_request(self, employee_id: str, action: str, params: dict, idempotency_key: str | None = None) -> dict:
        params = validate_action(action, params)
        if idempotency_key and (employee_id, idempotency_key) in self._by_key:  # BR08 for approval requests
            return dict(self._requests[self._by_key[(employee_id, idempotency_key)]])
        request_id = f"PRV-{next(self._ids):04d}"
        record = {"request_id": request_id, "employee_id": employee_id, "action": action, "params": params,
                  "binding": self._binding(request_id, employee_id, action, params), "status": PENDING,
                  "created_at": self._clock(), "decided_by": None, "decided_at": None, "expires_at": None,
                  "reason": ""}
        self._requests[request_id] = record
        if idempotency_key:
            self._by_key[(employee_id, idempotency_key)] = request_id
        return dict(record)

    def decide(self, approver_id: str, request_id: str, decision: str, reason: str = "") -> dict:
        if not self.is_approver(approver_id):
            raise ApprovalError("not_an_approver")
        if decision not in ("approve", "reject"):
            raise ApprovalError("invalid_decision")
        record = self._requests.get(request_id)
        if record is None:
            raise ApprovalError("unknown_request")
        if approver_id == record["employee_id"]:
            raise ApprovalError("self_approval")
        if record["status"] != PENDING:
            raise ApprovalError("already_decided")
        now = self._clock()
        record.update(status=APPROVED if decision == "approve" else REJECTED, decided_by=approver_id,
                      decided_at=now, reason=reason[:200],
                      expires_at=now + self._ttl if decision == "approve" else None)
        return dict(record)

    def check_execution(self, employee_id: str, request_id: str, action: str, params: dict) -> dict:
        """Return the approval if it permits exactly this execution, else raise ApprovalError(code)."""
        record = self._requests.get(request_id) if isinstance(request_id, str) else None
        if record is None:
            raise ApprovalError("unknown_request")
        if record["employee_id"] != employee_id:
            raise ApprovalError("wrong_employee")
        if record["status"] == PENDING:
            raise ApprovalError("pending")
        if record["status"] == REJECTED:
            raise ApprovalError("rejected")
        if record["status"] == USED:
            raise ApprovalError("already_used")
        if self._clock() > record["expires_at"]:
            raise ApprovalError("expired")
        if record["action"] != action:
            raise ApprovalError("action_mismatch")
        if self._binding(request_id, employee_id, action, params) != record["binding"]:
            raise ApprovalError("params_changed")
        return dict(record)

    def mark_used(self, request_id: str) -> None:
        self._requests[request_id]["status"] = USED

    def get(self, request_id: str):
        record = self._requests.get(request_id)
        return dict(record) if record else None

    def request_ids(self) -> list[str]:
        """Every request ID created so far, oldest first."""
        return list(self._requests)

    def display_status(self, request_id: str) -> str | None:
        record = self._requests.get(request_id)
        if record is None:
            return None
        if record["status"] == APPROVED and self._clock() > record["expires_at"]:
            return EXPIRED
        return record["status"]
