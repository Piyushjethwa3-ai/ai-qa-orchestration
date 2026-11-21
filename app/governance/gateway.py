"""
The tool gateway: the ONE place every tool call passes through, whoever makes it (the agent, or a direct
API caller trying to bypass the agent). It enforces, in code:

- default deny: unknown tools and prohibited operations are refused (permission matrix)
- identity: the employee is the trusted session identity; a different employee_id in the parameters is refused
- no smuggled authority: parameters outside a tool's allowed list ("approved", "role", "bypass" ...) are refused
- confirmation and approval requirements are present before the tool runs (the tool re-checks them in full)
- an audit record, redacted, for EVERY attempt: allowed or denied (BR12)

If the model asks for a restricted action anyway, it is blocked here and again inside the tool.
"""

from __future__ import annotations

from app.agent.tools import DENIED, SUCCESS, CallContext, ToolBackend, ToolResult
from app.governance import permissions
from app.governance.approvals import ApprovalError, ApprovalService
from app.governance.audit import AuditLog


class Gateway:
    def __init__(self, backend: ToolBackend, approvals: ApprovalService, audit: AuditLog):
        self.backend = backend
        self.approvals = approvals
        self.audit = audit

    # -- audit helper ----------------------------------------------------------------------------------
    def _log(self, ctx: CallContext, tool: str, params: dict, decision: str, reason: str, result_status,
             *, correlation_id=None, error=None):
        self.audit.record(request_id=ctx.request_id, session_id=ctx.session_id, actor_role=ctx.role,
                          actor_id=ctx.employee_id, tool=tool, params=params, decision=decision, reason=reason,
                          result_status=result_status, error=error,
                          confirmation_id=params.get("confirmation_id") if isinstance(params, dict) else None,
                          correlation_id=correlation_id)

    def _refuse(self, ctx, tool, params, reason, message) -> ToolResult:
        self._log(ctx, tool, params, "DENIED", reason, None, error=message)
        return ToolResult(tool, DENIED, error=message)

    # -- tool calls ----------------------------------------------------------------------------------------
    def invoke(self, ctx: CallContext, tool: str, params: dict) -> ToolResult:
        params = dict(params) if isinstance(params, dict) else {}
        required = permissions.classify(ctx.role, tool)
        if required == permissions.PROHIBITED:
            known = tool in permissions.MATRIX or tool in permissions.ALWAYS_PROHIBITED
            return self._refuse(ctx, tool, params, "prohibited_operation" if known else "unknown_tool",
                                "this operation is not permitted for this role" if known else "unknown tool")
        if "employee_id" in params and params["employee_id"] != ctx.employee_id:
            return self._refuse(ctx, tool, params, "employee_id_mismatch",
                                "an action may only be taken for the signed-in employee")
        extra = sorted(set(params) - permissions.PARAM_KEYS.get(tool, frozenset()) - {"employee_id"})
        if extra:
            return self._refuse(ctx, tool, params, "unexpected_parameter:" + ",".join(extra),
                                "unexpected parameters are not accepted")
        if params.get("target_employee_id") not in (None, ctx.employee_id):
            return self._refuse(ctx, tool, params, "cross_employee_target",
                                "an action may only target the signed-in employee")
        if required in (permissions.CONFIRMATION_REQUIRED, permissions.APPROVAL_REQUIRED) and not params.get("confirmation_id"):
            return self._refuse(ctx, tool, params, "confirmation_required", "employee confirmation is required")
        if required == permissions.APPROVAL_REQUIRED and not params.get("request_id"):
            return self._refuse(ctx, tool, params, "approval_required", "a matching IT approval is required")

        result = self.backend.invoke(tool, {**params, "employee_id": ctx.employee_id})
        correlation = params.get("request_id") or result.data.get("request_id")
        detail = result.internal or result.error  # the audit log (approver-only) keeps the precise reason
        reason = "" if result.status == SUCCESS else (detail or "")
        self._log(ctx, tool, params, "ALLOWED", reason, result.status, correlation_id=correlation,
                  error=detail if result.status != SUCCESS else None)
        return result

    # -- IT approver decisions and audit reading (never reachable from chat) -----------------------------------
    def decide_approval(self, approver_id: str, request_id: str, decision: str, reason: str = "", session_id="approver-api"):
        ctx = CallContext(employee_id=approver_id, session_id=session_id, request_id=request_id, role="it_approver")
        params = {"request_id": request_id, "decision": decision}
        if permissions.classify(ctx.role, "decide_approval") == permissions.PROHIBITED:
            self._log(ctx, "decide_approval", params, "DENIED", "prohibited_operation", None, correlation_id=request_id)
            raise ApprovalError("not_an_approver")
        try:
            record = self.approvals.decide(approver_id, request_id, decision, reason)
        except ApprovalError as exc:
            self._log(ctx, "decide_approval", params, "DENIED", exc.code, None, correlation_id=request_id)
            raise
        self._log(ctx, "decide_approval", params, "ALLOWED", "", record["status"], correlation_id=request_id)
        return record

    def read_audit(self, approver_id: str, **filters) -> list[dict]:
        ctx = CallContext(employee_id=approver_id, session_id="approver-api", request_id="", role="it_approver")
        self._log(ctx, "read_audit_log", dict(filters), "ALLOWED", "", SUCCESS)
        records = self.audit.records()
        for key, value in filters.items():
            if value is not None:
                records = [r for r in records if r.get(key) == value]
        return records
