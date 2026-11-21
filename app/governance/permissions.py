"""
The permission matrix: which role may do what, decided in code, outside the model.

Four classes of operation:

- ALLOWED               the role may do it (data is still limited to the caller's own records)
- CONFIRMATION_REQUIRED the role may do it only after the employee's recorded confirmation (BR06)
- APPROVAL_REQUIRED     the role may do it only with a matching, valid IT approval (BR06, BR07)
- PROHIBITED            never, for that role

Anything not listed is PROHIBITED (default deny). `policies/day6_permission_matrix.md` documents this
table and a test checks the two agree. Chat text, documents and tool output cannot change this table.
"""

from __future__ import annotations

ALLOWED, CONFIRMATION_REQUIRED, APPROVAL_REQUIRED, PROHIBITED = (
    "ALLOWED", "CONFIRMATION_REQUIRED", "APPROVAL_REQUIRED", "PROHIBITED")
CLASSES = (ALLOWED, CONFIRMATION_REQUIRED, APPROVAL_REQUIRED, PROHIBITED)
ROLES = ("employee", "agent", "it_approver")

_BOTH = lambda cls: {"employee": cls, "agent": cls, "it_approver": PROHIBITED}  # noqa: E731
_EVERYONE = {"employee": ALLOWED, "agent": ALLOWED, "it_approver": ALLOWED}

MATRIX: dict[str, dict[str, str]] = {
    "get_service_status": dict(_EVERYONE),
    "retrieve_guide": dict(_EVERYONE),
    "search_tickets": _BOTH(ALLOWED),
    "get_ticket": _BOTH(ALLOWED),
    "create_ticket": _BOTH(CONFIRMATION_REQUIRED),
    "request_privileged_action": _BOTH(CONFIRMATION_REQUIRED),
    "execute_privileged_action": _BOTH(APPROVAL_REQUIRED),
    "get_privileged_request_status": _BOTH(ALLOWED),
    "decide_approval": {"employee": PROHIBITED, "agent": PROHIBITED, "it_approver": ALLOWED},
    "read_audit_log": {"employee": PROHIBITED, "agent": PROHIBITED, "it_approver": ALLOWED},
}

# Operations no role may ever perform. No tool exists for them; an attempt is still denied and audited.
ALWAYS_PROHIBITED = ("grant_permission", "change_identity", "approve_own_request", "disable_audit",
                     "modify_audit_record", "read_other_employee_ticket")

# The only parameters a tool call may carry (employee_id is added by the gateway from the trusted session).
PARAM_KEYS: dict[str, frozenset] = {
    "get_service_status": frozenset({"service"}),
    "retrieve_guide": frozenset({"query", "os"}),
    "search_tickets": frozenset(),
    "get_ticket": frozenset({"ticket_id"}),
    "create_ticket": frozenset({"subject", "description", "idempotency_key", "confirmation_id"}),
    "request_privileged_action": frozenset({"action", "target_employee_id", "application", "confirmation_id",
                                            "idempotency_key"}),
    "execute_privileged_action": frozenset({"request_id", "action", "action_params", "confirmation_id",
                                            "idempotency_key"}),
    "get_privileged_request_status": frozenset({"request_id"}),
}


def classify(role: str, tool: str) -> str:
    """Return the class for (role, tool). Unknown roles and unknown tools are PROHIBITED."""
    if tool in ALWAYS_PROHIBITED:
        return PROHIBITED
    return MATRIX.get(tool, {}).get(role, PROHIBITED)
