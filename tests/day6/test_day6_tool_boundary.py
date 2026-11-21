"""
Day 6: attacks at the actual TOOL boundary (the gateway and the tools behind it), not at the prompt.

Each attack has a "would this test notice?" partner at the bottom: with the control removed, the same
attack SUCCEEDS, which proves the normal tests are sensitive to the control and not vacuous.
"""

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, _offline_and_isolated, clock, confirmed, ctx,  # noqa: F401
                          execute, stack, submit_reset)

from app.governance.approvals import ApprovalService
from app.governance.stack import build_governed_stack

TICKET = {"subject": "VPN problem", "description": "VPN fails"}


# -- cross-user access (BR01, BR02) --------------------------------------------------------------------------
def test_cross_user_ticket_read_is_denied_at_the_tool_and_leaks_nothing(clock):
    stack = build_governed_stack(clock=clock)  # seeded tickets
    result = stack.gateway.invoke(ctx(EMPLOYEE_B), "get_ticket", {"ticket_id": "TCK-1001"})
    assert result.status == "DENIED" and result.data == {} and "VPN client" not in repr(result)
    own = stack.gateway.invoke(ctx(EMPLOYEE_B), "search_tickets", {})
    assert {t["ticket_id"] for t in own.data["tickets"]} == {"TCK-1002", "TCK-1006"}


def test_acting_as_another_employee_in_the_parameters_is_refused_and_audited(stack):
    result = stack.gateway.invoke(ctx(EMPLOYEE_A), "search_tickets", {"employee_id": EMPLOYEE_B})
    assert result.status == "DENIED"
    assert stack.extras["audit"].records()[-1]["reason"] == "employee_id_mismatch"


@pytest.mark.parametrize("smuggled", [{"approved": True}, {"role": "it_approver"}, {"approval_id": "PRV-0001"},
                                      {"bypass": "yes"}, {"is_admin": True}])
def test_authority_cannot_be_smuggled_in_as_parameters(stack, smuggled):
    result = stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn", **smuggled})
    assert result.status == "DENIED"
    assert stack.extras["audit"].records()[-1]["reason"].startswith("unexpected_parameter:")


@pytest.mark.parametrize("tool", ["grant_permission", "change_identity", "approve_own_request", "disable_audit",
                                  "modify_audit_record", "read_other_employee_ticket", "delete_everything",
                                  "decide_approval", "read_audit_log"])
@pytest.mark.parametrize("role", ["employee", "agent"])
def test_prohibited_and_unknown_operations_are_denied_for_employees_and_the_agent(stack, tool, role):
    result = stack.gateway.invoke(ctx(role=role), tool, {})
    assert result.status == "DENIED"
    assert stack.extras["audit"].records()[-1]["reason"] in ("prohibited_operation", "unknown_tool")


def test_no_tool_exists_that_could_approve_or_change_permissions(stack):
    names = set(stack.backend.tool_names)
    assert not names & {"decide_approval", "approve", "grant_permission", "change_identity", "read_audit_log"}


def test_an_it_approver_cannot_use_employee_tools(stack):
    for tool in ("create_ticket", "execute_privileged_action", "get_ticket", "search_tickets"):
        assert stack.gateway.invoke(ctx(APPROVER, role="it_approver"), tool, {}).status == "DENIED"


def test_cross_employee_target_for_a_privileged_request_is_refused_by_gateway_and_tool(stack):
    params = {"action": "password_reset", "target_employee_id": EMPLOYEE_B}
    cid = confirmed(stack, EMPLOYEE_A, "request_privileged_action", params)
    full = {**params, "confirmation_id": cid, "idempotency_key": "k"}
    assert stack.gateway.invoke(ctx(EMPLOYEE_A), "request_privileged_action", full).status == "DENIED"
    assert stack.extras["audit"].records()[-1]["reason"] == "cross_employee_target"
    direct = stack.backend.invoke("request_privileged_action", {**full, "employee_id": EMPLOYEE_A})
    assert direct.status == "DENIED" and not stack.extras["approvals"]._requests  # the tool refuses on its own


# -- bypassing the agent: direct calls without confirmation or approval ------------------------------------------
def test_direct_ticket_creation_needs_a_recorded_confirmation(stack):
    base = {**TICKET, "idempotency_key": "k"}
    assert stack.gateway.invoke(ctx(), "create_ticket", base).status == "DENIED"           # none at all
    assert stack.gateway.invoke(ctx(), "create_ticket", {**base, "confirmation_id": "CONF-9999"}).status == "DENIED"
    proposed = stack.confirmations.propose(EMPLOYEE_A, "direct-api", "create_ticket", TICKET)
    assert stack.gateway.invoke(ctx(), "create_ticket", {**base, "confirmation_id": proposed}).status == "DENIED"
    other = confirmed(stack, EMPLOYEE_B, "create_ticket", TICKET)
    assert stack.gateway.invoke(ctx(), "create_ticket", {**base, "confirmation_id": other}).status == "DENIED"
    assert stack.backend.tickets == []


def test_ticket_creation_still_works_with_a_valid_confirmation_and_is_idempotent(stack):
    cid = confirmed(stack, EMPLOYEE_A, "create_ticket", TICKET)
    params = {**TICKET, "idempotency_key": "k", "confirmation_id": cid}
    first = stack.gateway.invoke(ctx(), "create_ticket", params)
    again = stack.gateway.invoke(ctx(), "create_ticket", params)
    assert first.status == again.status == "SUCCESS" and len(stack.backend.tickets) == 1


def test_direct_execution_without_approval_is_denied_by_gateway_and_by_the_tool(stack):
    rid = submit_reset(stack)  # still PENDING
    assert execute(stack, rid).status == "DENIED"
    assert "pending" in stack.extras["audit"].records()[-1]["error"]
    bare = stack.gateway.invoke(ctx(), "execute_privileged_action", {"action": "password_reset"})
    assert bare.status == "DENIED"  # no confirmation / request id at all
    cid = confirmed(stack, EMPLOYEE_A, "execute_privileged_action",
                    {"request_id": rid, "action": "password_reset", "action_params": {"target_employee_id": EMPLOYEE_A}})
    direct = stack.backend.invoke("execute_privileged_action", {
        "employee_id": EMPLOYEE_A, "request_id": rid, "action": "password_reset",
        "action_params": {"target_employee_id": EMPLOYEE_A}, "confirmation_id": cid, "idempotency_key": "x"})
    assert direct.status == "DENIED" and stack.extras["executions"] == {}  # calling the backend directly also fails


def test_a_made_up_or_foreign_request_id_cannot_execute(stack):
    assert execute(stack, "PRV-9999").status == "DENIED"
    other_rid = submit_reset(stack, employee=EMPLOYEE_B, key="kb")
    stack.gateway.decide_approval(APPROVER, other_rid, "approve")
    result = execute(stack, other_rid, employee=EMPLOYEE_A)  # EMP001 tries to use EMP002's approved request
    assert result.status == "DENIED" and "wrong_employee" in stack.extras["audit"].records()[-1]["error"]
    assert stack.extras["executions"] == {}


# -- the approval rules at execution time (BR07) -----------------------------------------------------------------
def test_changed_parameters_after_approval_are_refused_then_the_original_still_works(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    changed = execute(stack, rid, action_params={"target_employee_id": EMPLOYEE_B}, key="k1")
    assert changed.status == "DENIED" and "params_changed" in stack.extras["audit"].records()[-1]["error"]
    assert stack.extras["approvals"].get(rid)["status"] == "APPROVED"
    assert execute(stack, rid, key="k2").status == "SUCCESS"


def test_changed_action_after_approval_is_refused(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    result = execute(stack, rid, action="software_access_grant",
                     action_params={"target_employee_id": EMPLOYEE_A, "application": "x"})
    assert result.status == "DENIED" and "action_mismatch" in stack.extras["audit"].records()[-1]["error"]


def test_a_valid_approval_replayed_for_another_employee_is_refused(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    result = execute(stack, rid, employee=EMPLOYEE_B, action_params={"target_employee_id": EMPLOYEE_B})
    assert result.status == "DENIED" and stack.extras["executions"] == {}


def test_a_used_approval_cannot_execute_a_second_time(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    assert execute(stack, rid, key="k1").status == "SUCCESS"
    again = execute(stack, rid, key="k2")  # a new attempt, not a retry of the first
    assert again.status == "DENIED" and "already_used" in stack.extras["audit"].records()[-1]["error"]
    assert len(stack.extras["executions"]) == 1


def test_rejected_and_expired_approvals_cannot_execute(stack, clock):
    rejected = submit_reset(stack, key="k1")
    stack.gateway.decide_approval(APPROVER, rejected, "reject", "not verified")
    assert execute(stack, rejected).status == "DENIED"
    expiring = submit_reset(stack, key="k2")
    stack.gateway.decide_approval(APPROVER, expiring, "approve")
    clock.advance(901)
    result = execute(stack, expiring)
    assert result.status == "DENIED" and "expired" in stack.extras["audit"].records()[-1]["error"]
    assert stack.extras["executions"] == {}


def test_a_retry_after_a_timeout_never_executes_twice_but_a_new_attempt_is_refused(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    stack.backend.script_faults("execute_privileged_action", ["timeout_after_success"])
    action_params = {"target_employee_id": EMPLOYEE_A}
    cid = confirmed(stack, EMPLOYEE_A, "execute_privileged_action",
                    {"request_id": rid, "action": "password_reset", "action_params": action_params})
    call = {"request_id": rid, "action": "password_reset", "action_params": action_params,
            "confirmation_id": cid, "idempotency_key": "same-key"}
    assert stack.gateway.invoke(ctx(), "execute_privileged_action", call).status == "TIMEOUT"
    replay = stack.gateway.invoke(ctx(), "execute_privileged_action", call)  # the SAME request, retried
    assert replay.status == "SUCCESS" and replay.data["replayed"] is True
    assert len(stack.extras["executions"]) == 1
    assert execute(stack, rid, key="different-key").status == "DENIED"       # a different attempt is a reuse


def test_the_privileged_request_itself_is_idempotent(stack):
    params = {"action": "password_reset", "target_employee_id": EMPLOYEE_A}
    cid = confirmed(stack, EMPLOYEE_A, "request_privileged_action", params)
    call = {**params, "confirmation_id": cid, "idempotency_key": "k"}
    first = stack.gateway.invoke(ctx(), "request_privileged_action", call)
    again = stack.gateway.invoke(ctx(), "request_privileged_action", call)
    assert first.status == again.status == "PENDING_APPROVAL"
    assert first.data["request_id"] == again.data["request_id"] and again.data["replayed"] is True
    assert len(stack.extras["approvals"]._requests) == 1


def test_simulated_execution_is_labelled_simulated_and_touches_no_real_account(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve")
    result = execute(stack, rid)
    assert result.status == "SUCCESS" and result.data["simulated"] is True
    assert "No real account or password was changed" in result.data["result"]


# -- "would the test notice?" -----------------------------------------------------------------------------------
def test_sensitivity_removing_the_approval_check_lets_the_unapproved_attack_through(stack, monkeypatch):
    rid = submit_reset(stack)  # never approved
    assert execute(stack, rid).status == "DENIED"  # the real behaviour
    monkeypatch.setattr(ApprovalService, "check_execution", lambda self, e, r, a, p: {"status": "APPROVED"})
    monkeypatch.setattr(ApprovalService, "mark_used", lambda self, r: None)
    assert execute(stack, rid, key="k9").status == "SUCCESS"  # so the tests above WOULD fail if the check were removed


def test_sensitivity_removing_the_confirmation_check_lets_a_forged_write_through(stack, monkeypatch):
    base = {**TICKET, "idempotency_key": "k", "confirmation_id": "CONF-9999"}
    assert stack.gateway.invoke(ctx(), "create_ticket", base).status == "DENIED"
    monkeypatch.setattr("app.agent.confirmations.ConfirmationStore.validate", lambda self, *a, **k: {})
    monkeypatch.setattr("app.agent.confirmations.ConfirmationStore.consume", lambda self, cid: None)
    assert stack.gateway.invoke(ctx(), "create_ticket", base).status == "SUCCESS"


def test_sensitivity_removing_the_ownership_check_leaks_the_ticket(clock, monkeypatch):
    stack = build_governed_stack(clock=clock)
    assert stack.gateway.invoke(ctx(EMPLOYEE_B), "get_ticket", {"ticket_id": "TCK-1001"}).status == "DENIED"
    monkeypatch.setattr("app.agent.tools.rules.employee_owns_ticket", lambda ticket, employee_id: True)
    assert stack.gateway.invoke(ctx(EMPLOYEE_B), "get_ticket", {"ticket_id": "TCK-1001"}).status == "SUCCESS"


def test_sensitivity_removing_the_permission_matrix_lets_the_prohibited_call_reach_the_tool(stack, monkeypatch):
    approver = ctx(APPROVER, role="it_approver")
    call = {"ticket_id": "TCK-1001"}
    assert stack.gateway.invoke(approver, "get_ticket", call).status == "DENIED"  # real behaviour
    assert stack.extras["audit"].records()[-1]["reason"] == "prohibited_operation"
    monkeypatch.setattr("app.governance.permissions.classify", lambda role, tool: "ALLOWED")
    # With the matrix removed the call reaches the tool (this stack has no tickets, so the tool says NOT_FOUND).
    assert stack.gateway.invoke(approver, "get_ticket", call).status == "NOT_FOUND"
