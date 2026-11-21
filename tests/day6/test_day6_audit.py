"""Day 6: the audit log (BR05, BR12): every attempt recorded, secrets removed, tampering detectable."""

import copy
import json

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, FIXED_AUDIT_TIME, _offline_and_isolated, clock,  # noqa: F401
                          confirmed, ctx, execute, stack, submit_reset)

from app.governance.audit import AuditLog
from app.governance.stack import build_governed_stack

REQUIRED = {"audit_id", "seq", "timestamp", "request_id", "session_id", "actor_role", "actor_id", "tool", "params",
            "decision", "reason", "result_status", "correlation_id", "prev_hash", "hash"}


def test_every_attempt_is_recorded_allowed_or_denied(stack):
    attempts = [
        (ctx(), "get_service_status", {"service": "vpn"}),                       # allowed
        (ctx(), "get_ticket", {"ticket_id": "TCK-9999"}),                         # allowed by policy, tool says NOT_FOUND
        (ctx(), "grant_permission", {"role": "admin"}),                           # prohibited
        (ctx(), "get_service_status", {"service": "vpn", "approved": True}),     # smuggled parameter
        (ctx(), "create_ticket", {"subject": "x", "description": "y", "idempotency_key": "k"}),  # no confirmation
        (ctx(EMPLOYEE_A), "search_tickets", {"employee_id": EMPLOYEE_B}),         # acting as someone else
    ]
    for context, tool, params in attempts:
        stack.gateway.invoke(context, tool, params)
    records = stack.extras["audit"].records()
    assert len(records) == len(attempts)
    assert [r["tool"] for r in records] == [a[1] for a in attempts]
    assert [r["decision"] for r in records] == ["ALLOWED", "ALLOWED", "DENIED", "DENIED", "DENIED", "DENIED"]
    assert [r["result_status"] for r in records][:2] == ["SUCCESS", "NOT_FOUND"]


def test_records_have_the_required_fields_and_sequence(stack):
    stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn"})
    stack.gateway.invoke(ctx(), "grant_permission", {})
    records = stack.extras["audit"].records()
    assert all(REQUIRED <= set(r) for r in records)
    assert [r["seq"] for r in records] == [1, 2] and [r["audit_id"] for r in records] == ["AUD-000001", "AUD-000002"]
    assert all(r["timestamp"] == FIXED_AUDIT_TIME and r["actor_role"] == "employee" for r in records)


def test_secrets_in_parameters_and_errors_are_redacted_before_storage(stack):
    secret_params = {"service": "vpn", "password": "hunter2", "note": "my otp is 482913"}
    stack.gateway.invoke(ctx(), "get_service_status", secret_params)  # refused (unexpected parameters), still audited
    stack.gateway.invoke(ctx(), "create_ticket", {"subject": "my password is hunter2", "description": "token: abc12345",
                                                  "idempotency_key": "k"})
    blob = json.dumps(stack.extras["audit"].records())
    for secret in ("hunter2", "482913", "abc12345"):
        assert secret not in blob
    assert "[REDACTED]" in blob


def test_a_secret_in_a_direct_ticket_is_not_stored_in_the_ticket_either(stack):
    params = {"subject": "VPN broke, my password is hunter2", "description": "api key = zzz-12345 please help"}
    cid = confirmed(stack, EMPLOYEE_A, "create_ticket", params)
    result = stack.gateway.invoke(ctx(), "create_ticket", {**params, "idempotency_key": "k", "confirmation_id": cid})
    assert result.status == "SUCCESS"
    stored = json.dumps(stack.backend.tickets)
    assert "hunter2" not in stored and "zzz-12345" not in stored and "[REDACTED]" in stored


def test_the_confirmation_text_covers_the_raw_request_so_changing_it_is_still_refused(stack):
    params = {"subject": "my password is hunter2", "description": "d"}
    cid = confirmed(stack, EMPLOYEE_A, "create_ticket", params)
    changed = {**params, "subject": "my password is other", "idempotency_key": "k", "confirmation_id": cid}
    assert stack.gateway.invoke(ctx(), "create_ticket", changed).status == "DENIED"


def test_the_request_approval_and_result_share_one_correlation_id(stack):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "approve", "verified")
    assert execute(stack, rid).status == "SUCCESS"
    linked = stack.extras["audit"].for_correlation(rid)
    assert [(r["tool"], r["actor_role"]) for r in linked] == [
        ("request_privileged_action", "employee"), ("decide_approval", "it_approver"),
        ("execute_privileged_action", "employee")]
    assert {r["actor_id"] for r in linked} == {EMPLOYEE_A, APPROVER}
    assert [r["result_status"] for r in linked] == ["PENDING_APPROVAL", "APPROVED", "SUCCESS"]
    assert all(r["request_id"] for r in linked)


def test_denied_approval_decisions_are_audited_too(stack):
    rid = submit_reset(stack)
    for impostor in (EMPLOYEE_A, "ADMIN"):
        with pytest.raises(Exception):
            stack.gateway.decide_approval(impostor, rid, "approve")
    decisions = [r for r in stack.extras["audit"].records() if r["tool"] == "decide_approval"]
    assert [r["decision"] for r in decisions] == ["DENIED", "DENIED"]
    assert [r["reason"] for r in decisions] == ["not_an_approver", "not_an_approver"]
    assert stack.extras["approvals"].get(rid)["status"] == "PENDING"


def test_reading_the_audit_log_is_itself_audited_and_filterable(stack):
    stack.gateway.invoke(ctx(request_id="R-1"), "get_service_status", {"service": "vpn"})
    stack.gateway.invoke(ctx(request_id="R-2"), "get_service_status", {"service": "vpn"})
    only = stack.gateway.read_audit(APPROVER, request_id="R-2")
    assert [r["request_id"] for r in only] == ["R-2"]
    assert stack.extras["audit"].records()[-1]["tool"] == "read_audit_log"


# -- tamper evidence ------------------------------------------------------------------------------------------
def _log_with_records(n=5) -> AuditLog:
    log = AuditLog(clock=lambda: FIXED_AUDIT_TIME)
    for i in range(n):
        log.record(request_id=f"R-{i}", tool="get_service_status", decision="ALLOWED", params={"service": "vpn"})
    return log


def test_an_intact_chain_verifies():
    assert _log_with_records().verify_chain() == (True, None)
    assert AuditLog().verify_chain() == (True, None)


def test_editing_a_record_is_detected():
    log = _log_with_records()
    tampered = log.records()
    tampered[2]["decision"] = "DENIED"
    assert log.verify_chain(tampered) == (False, 2)


def test_deleting_a_record_is_detected():
    log = _log_with_records()
    records = log.records()
    del records[1]
    assert log.verify_chain(records) == (False, 1)


def test_reordering_records_is_detected():
    log = _log_with_records()
    records = log.records()
    records[1], records[2] = records[2], records[1]
    assert log.verify_chain(records)[0] is False


def test_the_copy_returned_by_records_cannot_alter_the_log():
    log = _log_with_records()
    copy_ = log.records()
    copy_[0]["decision"] = "DENIED"
    copy_.clear()
    assert len(log.records()) == 5 and log.verify_chain() == (True, None)


def test_file_sink_is_json_lines_redacted_and_verifiable(tmp_path):
    path = tmp_path / "audit" / "audit.jsonl"
    stack = build_governed_stack(tickets=[], audit_path=path, audit_clock=lambda: FIXED_AUDIT_TIME)
    stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn", "password": "hunter2"})
    stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn"})
    text = path.read_text()
    assert "hunter2" not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert len(lines) == 2 and stack.extras["audit"].verify_chain(lines) == (True, None)
    lines[0] = copy.deepcopy(lines[0]) | {"decision": "ALLOWED"}
    assert stack.extras["audit"].verify_chain(lines) == (False, 0)


def test_known_limit_a_chain_can_be_recomputed_by_someone_who_rewrites_the_whole_file():
    """Hash chaining makes edits DETECTABLE, not impossible. This records the limit honestly."""
    from app.governance.audit import GENESIS, _digest

    forged = [{"seq": 1, "tool": "x", "decision": "ALLOWED", "prev_hash": GENESIS}]
    forged[0]["hash"] = _digest(GENESIS, forged[0])
    assert AuditLog().verify_chain(forged) == (True, None)
