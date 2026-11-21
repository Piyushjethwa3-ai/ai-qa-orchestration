"""
Simulated privileged tools. NOTHING real happens here: no account is touched and no password exists
anywhere in this code. A "password reset" is a record that says the simulation ran.

The approval check lives INSIDE the tool handler, not only in the gateway, so calling the backend
directly cannot run a privileged action without a matching approval.
"""

from __future__ import annotations

from app.agent.confirmations import ConfirmationError, fingerprint
from app.agent.tools import DENIED, NOT_FOUND, PENDING_APPROVAL, SUCCESS, ToolBackend, ToolError, ToolResult
from app.governance.approvals import ApprovalError, ApprovalService, validate_action


# Approval failures that would reveal whether a request ID exists, if a caller could tell them apart.
HIDDEN_CODES = ("unknown_request", "wrong_employee")


def install(backend: ToolBackend, approvals: ApprovalService) -> dict:
    """Register the privileged tools on `backend`. Returns the execution ledger (request_id -> record)."""
    executions: dict[str, dict] = {}
    request_keys: dict[tuple, str] = {}

    def request_privileged_action(params: dict) -> ToolResult:
        employee_id = params["employee_id"]
        action = params.get("action")
        required = {k: params[k] for k in ("target_employee_id", "application") if k in params}
        try:
            clean = validate_action(action, required)
        except ApprovalError as exc:
            raise ToolError(str(exc))
        if clean["target_employee_id"] != employee_id:  # an employee may only ask for their own account
            return ToolResult("request_privileged_action", DENIED, error="cannot request an action for another employee")
        content = {"action": action, **clean}
        key = params.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise ToolError("missing idempotency_key")
        existing = request_keys.get((employee_id, key))
        if existing is not None:  # BR08: a retry returns the same request, never a second one
            existing_id, existing_hash = existing
            if existing_hash != fingerprint(content):
                raise ToolError("idempotency key was already used with different parameters")
            return ToolResult("request_privileged_action", PENDING_APPROVAL,
                              data={"request_id": existing_id, "approval_status": approvals.display_status(existing_id),
                                    "replayed": True})
        try:
            backend.confirmations.validate(employee_id, "request_privileged_action", content, params.get("confirmation_id"))
        except ConfirmationError as exc:
            return ToolResult("request_privileged_action", DENIED, error=f"confirmation required ({exc.code})",
                              internal=f"confirmation required ({exc.internal})")
        record = approvals.create_request(employee_id, action, clean, idempotency_key=key)
        request_keys[(employee_id, key)] = (record["request_id"], fingerprint(content))
        backend.confirmations.consume(params["confirmation_id"])
        # PENDING_APPROVAL is its own status: the request is RECORDED, the action has NOT happened (BR11).
        return ToolResult("request_privileged_action", PENDING_APPROVAL,
                          data={"request_id": record["request_id"], "approval_status": "PENDING", "replayed": False})

    def execute_privileged_action(params: dict) -> ToolResult:
        employee_id = params["employee_id"]
        request_id, action, action_params = params.get("request_id"), params.get("action"), params.get("action_params")
        key = params.get("idempotency_key")
        binding = fingerprint({"action": action, "action_params": action_params})

        done = executions.get(request_id)
        if done and done["employee_id"] == employee_id and key and done["key"] == key and done["binding"] == binding:
            return ToolResult("execute_privileged_action", SUCCESS, data={**done["data"], "replayed": True})

        try:
            backend.confirmations.validate(employee_id, "execute_privileged_action",
                                           {"request_id": request_id, "action": action, "action_params": action_params},
                                           params.get("confirmation_id"))
        except ConfirmationError as exc:
            return ToolResult("execute_privileged_action", DENIED, error=f"confirmation required ({exc.code})",
                              internal=f"confirmation required ({exc.internal})")
        try:
            approvals.check_execution(employee_id, request_id, action, action_params)
        except ApprovalError as exc:
            if exc.code in HIDDEN_CODES:  # someone else's request and a request that does not exist look the SAME
                return ToolResult("execute_privileged_action", DENIED, error="approval not valid (not found)",
                                  internal=f"approval not valid ({exc.code})")
            return ToolResult("execute_privileged_action", DENIED, error=f"approval not valid ({exc.code})")
        if not isinstance(key, str) or not key:
            raise ToolError("missing idempotency_key")

        outcome = {"request_id": request_id, "action": action, "simulated": True,
                   "result": f"Simulated {action} was recorded. No real account or password was changed."}
        executions[request_id] = {"employee_id": employee_id, "key": key, "binding": binding, "data": outcome}
        approvals.mark_used(request_id)
        backend.confirmations.consume(params["confirmation_id"])
        return ToolResult("execute_privileged_action", SUCCESS, data={**outcome, "replayed": False})

    def get_privileged_request_status(params: dict) -> ToolResult:
        request_id = params.get("request_id")
        record = approvals.get(request_id) if isinstance(request_id, str) else None
        if record is None:
            return ToolResult("get_privileged_request_status", NOT_FOUND, error="request not found", internal="request not found")
        if record["employee_id"] != params["employee_id"]:  # identical to "does not exist"; the audit log keeps the truth
            return ToolResult("get_privileged_request_status", NOT_FOUND, error="request not found", internal="not your request")
        return ToolResult("get_privileged_request_status", SUCCESS, data={
            "request_id": request_id, "action": record["action"], "action_params": dict(record["params"]),
            "approval_status": approvals.display_status(request_id), "executed": request_id in executions})

    backend.register("request_privileged_action", request_privileged_action)
    backend.register("execute_privileged_action", execute_privileged_action)
    backend.register("get_privileged_request_status", get_privileged_request_status)
    return executions
