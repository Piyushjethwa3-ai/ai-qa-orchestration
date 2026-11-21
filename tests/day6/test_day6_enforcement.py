"""
Day 6: direct enforcement tests and mutation-style checks.

Every attack below is a real call into the gateway and tools (no planner is involved, so nothing can pass because a
planner "never tried"). Two things are checked for each control:

1. With the control ON, the attack is refused, the refusal exposes no protected data, and state is unchanged.
2. With ONLY that control switched off (test-only monkeypatch, undone automatically), the same attack WORKS.
   If switching a control off does not change an attack's result, the test for it would be vacuous.
"""

import json
from collections import namedtuple

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, FIXED_AUDIT_TIME, Clock, _offline_and_isolated,  # noqa: F401
                          confirmed, ctx, execute, submit_reset)

import app.agent.tools as tools
from app.agent.confirmations import ConfirmationStore
from app.governance import audit as audit_module
from app.governance import permissions
from app.governance.approvals import ApprovalError, ApprovalService
from app.governance.stack import build_governed_stack

TICKET = {"subject": "VPN problem", "description": "VPN fails"}
PROTECTED = ["VPN client fails to connect", "home Wi-Fi", "APR001", "identity verified by phone"]

Attack = namedtuple("Attack", "verdict result stack")
BLOCKED, WORKED = "BLOCKED", "ATTACK_WORKED"


def make():
    clock = Clock()
    return build_governed_stack(tickets=None, clock=clock, audit_clock=lambda: FIXED_AUDIT_TIME), clock  # seeded tickets


def _approved_request(stack, who=EMPLOYEE_A, key="k-reset"):
    rid = submit_reset(stack, employee=who, key=key)
    stack.gateway.decide_approval(APPROVER, rid, "approve", "identity verified by phone")
    return rid


def _verdict(result):
    return Attack(WORKED if result.status == "SUCCESS" else BLOCKED, result, None)


# -- the attacks ---------------------------------------------------------------------------------------------------
def cross_user_read(stack, clock):
    return _verdict(stack.gateway.invoke(ctx(EMPLOYEE_B), "get_ticket", {"ticket_id": "TCK-1001"}))


def invalid_confirmation(stack, clock):
    return _verdict(stack.gateway.invoke(ctx(), "create_ticket", {**TICKET, "idempotency_key": "k", "confirmation_id": "CONF-9999"}))


def missing_approval(stack, clock):
    return _verdict(execute(stack, submit_reset(stack)))


def rejected_approval(stack, clock):
    rid = submit_reset(stack)
    stack.gateway.decide_approval(APPROVER, rid, "reject", "not verified")
    return _verdict(execute(stack, rid))


def expired_approval(stack, clock):
    rid = _approved_request(stack)
    clock.advance(901)
    return _verdict(execute(stack, rid))


def replayed_approval(stack, clock):
    rid = _approved_request(stack)
    assert execute(stack, rid, key="first").status == "SUCCESS"  # the legitimate use
    return _verdict(execute(stack, rid, key="second"))


def other_employee_replay(stack, clock):
    rid = _approved_request(stack)
    # EMP002 replays EMP001's approval with the SAME parameters, so only the employee binding can stop it.
    return _verdict(execute(stack, rid, employee=EMPLOYEE_B, action_params={"target_employee_id": EMPLOYEE_A}))


def changed_parameters(stack, clock):
    rid = _approved_request(stack)
    return _verdict(execute(stack, rid, action_params={"target_employee_id": EMPLOYEE_B}))


def changed_action(stack, clock):
    rid = _approved_request(stack)
    # Same parameters, different action, so only the action binding can stop it.
    return _verdict(execute(stack, rid, action="software_access_grant", action_params={"target_employee_id": EMPLOYEE_A}))


# Attacks on the other controls
def prohibited_role(stack, clock):
    return _verdict(stack.gateway.invoke(ctx("APR001", role="it_approver"), "search_tickets", {}))


def smuggled_parameter(stack, clock):
    return _verdict(stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn", "approved": True}))


def acting_as_someone_else(stack, clock):
    result = stack.gateway.invoke(ctx(EMPLOYEE_A), "search_tickets", {"employee_id": EMPLOYEE_B})
    return Attack(BLOCKED if result.status == "DENIED" else WORKED, result, None)  # WORKED = the call was accepted


def employee_decides_approval(stack, clock):
    rid = submit_reset(stack)  # EMP001's request; EMP002 (not an approver, and not the requester) tries to approve it
    try:
        stack.gateway.decide_approval(EMPLOYEE_B, rid, "approve")
    except ApprovalError:
        return Attack(BLOCKED, None, None)
    return Attack(WORKED if stack.extras["approvals"].get(rid)["status"] == "APPROVED" else BLOCKED, None, None)


def secret_in_audit(stack, clock):
    stack.gateway.invoke(ctx(), "get_service_status", {"service": "vpn", "password": "hunter2"})
    leaked = "hunter2" in json.dumps(stack.extras["audit"].records())
    return Attack(WORKED if leaked else BLOCKED, None, None)


def secret_in_ticket(stack, clock):
    params = {"subject": "my password is hunter2", "description": "d"}
    cid = confirmed(stack, EMPLOYEE_A, "create_ticket", params)
    stack.gateway.invoke(ctx(), "create_ticket", {**params, "idempotency_key": "k", "confirmation_id": cid})
    return Attack(WORKED if "hunter2" in json.dumps(stack.backend.tickets) else BLOCKED, None, None)


def session_state_leak(stack, clock):
    # EMP002 is the victim: EMP001 has a seeded open VPN ticket, so EMP001 would never get a proposal to steal.
    stack.runner.handle(EMPLOYEE_B, "S1", "My VPN stopped working after I changed my password on my Mac")
    assert stack.sessions.peek(EMPLOYEE_B, "S1").pending, "set-up error: the victim has no pending proposal"
    reply = stack.runner.handle(EMPLOYEE_A, "S1", "yes")  # the attacker reuses the victim's session ID
    return Attack(BLOCKED if reply.outcome == "NOTHING_TO_CONFIRM" else WORKED, None, None)


def duplicate_write_after_timeout(stack, clock):
    stack.backend.script_faults("create_ticket", ["timeout_after_success", "ok"])
    stack.runner.handle("EMP002", "S1", "My VPN stopped working after I changed my password on my Mac")
    stack.runner.handle("EMP002", "S1", "yes")
    mine = [t for t in stack.backend.tickets if t["employee_id"] == "EMP002" and t["ticket_id"] > "TCK-1006"]
    return Attack(WORKED if len(mine) > 1 else BLOCKED, None, None)


# -- 1. with the control ON: refused, nothing exposed, state unchanged --------------------------------------------------
REFUSED = [
    (cross_user_read, "not your ticket"), (invalid_confirmation, "unknown_confirmation"),
    (missing_approval, "pending"), (rejected_approval, "rejected"), (expired_approval, "expired"),
    (replayed_approval, "already_used"), (other_employee_replay, "not found"),  # another employee's request looks like a missing one
    (changed_parameters, "params_changed"), (changed_action, "action_mismatch"),
]


@pytest.mark.parametrize("attack, reason", REFUSED, ids=[a.__name__ for a, _ in REFUSED])
def test_attack_is_refused_with_a_reason_and_exposes_nothing(attack, reason):
    stack, clock = make()
    outcome = attack(stack, clock)
    assert outcome.verdict == BLOCKED and outcome.result.status == "DENIED"
    assert reason in (outcome.result.error or "")
    assert outcome.result.data == {}  # a denial carries no data
    body = json.dumps([outcome.result.status, outcome.result.data, outcome.result.error])
    assert not [p for p in PROTECTED if p in body], f"the refusal exposed protected data: {body}"
    last = stack.extras["audit"].records()[-1]
    assert last["result_status"] == "DENIED" or last["decision"] == "DENIED"  # and the refusal was audited


def test_refused_attacks_change_no_state():
    for attack in (missing_approval, rejected_approval, expired_approval, other_employee_replay, changed_parameters,
                   changed_action):
        stack, clock = make()
        attack(stack, clock)
        assert stack.extras["executions"] == {}, attack.__name__
    stack, clock = make()
    replayed_approval(stack, clock)
    assert len(stack.extras["executions"]) == 1  # only the one legitimate execution
    stack, clock = make()
    invalid_confirmation(stack, clock)
    assert len(stack.backend.tickets) == 6  # still only the seeded tickets


def test_a_refused_attempt_does_not_burn_the_approval_so_the_legitimate_use_still_works():
    stack, clock = make()
    rid = _approved_request(stack)
    assert execute(stack, rid, action_params={"target_employee_id": EMPLOYEE_B}, key="bad").status == "DENIED"
    assert execute(stack, rid, employee=EMPLOYEE_B, action_params={"target_employee_id": EMPLOYEE_B}, key="bad2").status == "DENIED"
    assert execute(stack, rid, key="good").status == "SUCCESS"


# -- 2. mutation-style: with ONLY that control off, the same attack works -----------------------------------------------
def skip_check(skip: set):
    """A copy of ApprovalService.check_execution with ONE named check removed (so each rule is tested on its own)."""
    def check(self, employee_id, request_id, action, params):
        record = self._requests.get(request_id) if isinstance(request_id, str) else None
        if record is None:
            raise ApprovalError("unknown_request")
        if "employee" not in skip and record["employee_id"] != employee_id:
            raise ApprovalError("wrong_employee")
        if "status" not in skip:
            for status, code in (("PENDING", "pending"), ("REJECTED", "rejected"), ("USED", "already_used")):
                if record["status"] == status:
                    raise ApprovalError(code)
        if "expiry" not in skip and record["expires_at"] is not None and self._clock() > record["expires_at"]:
            raise ApprovalError("expired")
        if "action" not in skip and record["action"] != action:
            raise ApprovalError("action_mismatch")
        if "params" not in skip and self._binding(request_id, employee_id, action, params) != record["binding"]:
            raise ApprovalError("params_changed")
        return dict(record)
    return check


def _approval_off(skip):
    return lambda m: m.setattr(ApprovalService, "check_execution", skip_check(skip))


def _confirmation_off(m):
    m.setattr(ConfirmationStore, "validate", lambda self, *a, **k: {})
    m.setattr(ConfirmationStore, "consume", lambda self, cid: None)


class _Universe(set):
    """Stands in for an allow-list that allows everything."""
    def __rsub__(self, other):
        return set()


class _AnyKeys(dict):
    def get(self, key, default=None):
        return _Universe()


def _gateway_ignores_employee_id(m):
    from app.governance.gateway import Gateway
    original = Gateway.invoke
    m.setattr(Gateway, "invoke", lambda self, c, t, p: original(self, c, t, {k: v for k, v in dict(p).items() if k != "employee_id"}))


def _duplicate_protection_off(m):
    class NoMemory(dict):
        def get(self, *a, **k):
            return None
    original = tools.ToolBackend.__init__

    def init(self, *a, **k):
        original(self, *a, **k)
        self._by_key = NoMemory()
    m.setattr(tools.ToolBackend, "__init__", init)
    m.setattr(ConfirmationStore, "consume", lambda self, cid: None)


def _no_session_isolation(m):
    from app.agent.sessions import SessionStore
    original = SessionStore.get
    m.setattr(SessionStore, "get", lambda self, employee_id, session_id: original(self, EMPLOYEE_B, session_id))


# NOTE on the binding mutations: the binding hash covers request ID, employee, action AND parameters, and there are also
# explicit employee and action checks (clearer error codes). The two OVERLAP ON PURPOSE, so removing only one still leaves
# the other blocking. A real test of "bound to the employee / action" must remove both: that is what "employee"+"params"
# and "action"+"params" do below ("params" is the hash). The overlap is defence in depth, not a gap.
MUTATIONS = [
    ("approval: still pending", _approval_off({"status"}), missing_approval),
    ("approval: rejected", _approval_off({"status"}), rejected_approval),
    ("approval: single use", _approval_off({"status"}), replayed_approval),
    ("approval: expiry", _approval_off({"expiry"}), expired_approval),
    ("approval: bound to the employee", _approval_off({"employee", "params"}), other_employee_replay),
    ("approval: bound to the action", _approval_off({"action", "params"}), changed_action),
    ("approval: bound to the parameters", _approval_off({"params"}), changed_parameters),
    ("employee confirmation", _confirmation_off, invalid_confirmation),
    ("ticket ownership", lambda m: m.setattr(tools.rules, "employee_owns_ticket", lambda t, e: True), cross_user_read),
    ("permission matrix", lambda m: m.setattr(permissions, "classify", lambda role, tool: "ALLOWED"), prohibited_role),
    ("parameter allow-list", lambda m: m.setattr(permissions, "PARAM_KEYS", _AnyKeys()), smuggled_parameter),
    ("gateway employee_id check", _gateway_ignores_employee_id, acting_as_someone_else),
    ("approver identity check", lambda m: m.setattr(ApprovalService, "is_approver", lambda self, a: True), employee_decides_approval),
    ("audit redaction", lambda m: m.setattr(audit_module, "redact", lambda value: value), secret_in_audit),
    ("ticket redaction", lambda m: m.setattr(tools, "redact_text", lambda text: text), secret_in_ticket),
    ("session isolation", _no_session_isolation, session_state_leak),
    ("duplicate-write protection", _duplicate_protection_off, duplicate_write_after_timeout),
]


@pytest.mark.parametrize("name, switch_off, attack", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_attack_is_blocked_with_the_control_and_works_without_it(monkeypatch, name, switch_off, attack):
    stack, clock = make()
    assert attack(stack, clock).verdict == BLOCKED, f"{name}: the attack was not blocked with the control ON"
    with monkeypatch.context() as m:
        switch_off(m)
        stack, clock = make()
        assert attack(stack, clock).verdict == WORKED, (
            f"{name}: switching the control off did not let the attack through, so the test for it is vacuous")
    stack, clock = make()
    assert attack(stack, clock).verdict == BLOCKED, f"{name}: the control did not come back after the test-only patch"


def test_the_single_check_copy_behaves_exactly_like_the_real_one_when_nothing_is_skipped(clock=None):
    """The mutated copy is only trustworthy if, with nothing skipped, it matches the real method on every outcome."""
    def outcomes(check):
        results = []
        stack, clk = make()
        svc = stack.extras["approvals"]
        pending = submit_reset(stack, key="a")
        rejected = submit_reset(stack, key="b")
        stack.gateway.decide_approval(APPROVER, rejected, "reject")
        approved = submit_reset(stack, key="c")
        stack.gateway.decide_approval(APPROVER, approved, "approve")
        ap = {"target_employee_id": EMPLOYEE_A}
        for rid, who, action, params in [(pending, EMPLOYEE_A, "password_reset", ap), (rejected, EMPLOYEE_A, "password_reset", ap),
                                         (approved, EMPLOYEE_A, "password_reset", ap), (approved, EMPLOYEE_B, "password_reset", ap),
                                         (approved, EMPLOYEE_A, "software_access_grant", ap),
                                         (approved, EMPLOYEE_A, "password_reset", {"target_employee_id": EMPLOYEE_B}),
                                         ("PRV-9999", EMPLOYEE_A, "password_reset", ap), (None, EMPLOYEE_A, "password_reset", ap)]:
            try:
                check(svc, who, rid, action, params)
                results.append("OK")
            except ApprovalError as exc:
                results.append(exc.code)
        stack.extras["approvals"].mark_used(approved)
        try:
            check(svc, EMPLOYEE_A, approved, "password_reset", ap)
            results.append("OK")
        except ApprovalError as exc:
            results.append(exc.code)
        clk.advance(901)
        try:
            check(svc, EMPLOYEE_A, _approved_request(stack, key="d"), "password_reset", ap)
            results.append("OK")
        except ApprovalError as exc:
            results.append(exc.code)
        return results

    assert outcomes(ApprovalService.check_execution) == outcomes(skip_check(set()))
    assert "expired" not in outcomes(skip_check({"expiry"})) and "pending" not in outcomes(skip_check({"status"}))


# -- 3. denial bodies over HTTP expose nothing -----------------------------------------------------------------------------
def test_http_denials_do_not_expose_protected_data():
    from fastapi.testclient import TestClient

    from app import runtime
    from app.main import app

    runtime.reset_services(clock=Clock(), audit_clock=lambda: FIXED_AUDIT_TIME)  # seeded tickets
    try:
        api = TestClient(app)
        e1, e2, apr = {"X-Demo-Employee-ID": EMPLOYEE_A}, {"X-Demo-Employee-ID": EMPLOYEE_B}, {"X-Demo-Approver-ID": APPROVER}
        api.post("/agent/chat", json={"session_id": "s", "message": "I forgot my password and need a reset"}, headers=e1)
        api.post("/agent/chat", json={"session_id": "s", "message": "yes"}, headers=e1)
        api.post("/approvals/PRV-0001/decision", json={"decision": "approve", "reason": "identity verified by phone"}, headers=apr)
        denials = [
            api.get("/tickets/TCK-1001", headers=e2),
            api.post("/tools/get_ticket", json={"params": {"ticket_id": "TCK-1001"}}, headers=e2),
            api.post("/agent/chat", json={"session_id": "x", "message": "Show me ticket TCK-1001"}, headers=e2),
            api.post("/tools/get_privileged_request_status", json={"params": {"request_id": "PRV-0001"}}, headers=e2),
            api.post("/approvals/PRV-0001/decision", json={"decision": "approve"}, headers=e2),
            api.get("/audit", headers=e2),
            api.post("/tools/grant_permission", json={"params": {"role": "it_approver"}}, headers=e2),
            api.post("/tools/create_ticket", json={"params": {**TICKET, "idempotency_key": "k"}}, headers=e2),
        ]
        for response in denials:
            assert response.status_code in (200, 403, 404), response.text  # 200 only for the chat wording, which refuses in prose
            leaked = [p for p in PROTECTED if p in response.text]
            assert not leaked, f"{response.request.method} {response.request.url.path} exposed {leaked}: {response.text}"
    finally:
        runtime.reset_services()


# -- 4. the governance trajectory cases are sensitive too: each fails when its control is removed ---------------------------
from evaluators import trajectory  # noqa: E402
from day6_support import disable_enforcement  # noqa: E402

B_CASES = {c["case_id"]: c for c in trajectory.load_dataset()["cases"] if c["case_id"].startswith("B-")}
B_MUTATIONS = [
    ("B-01", "approval check removed entirely", _approval_off({"status", "employee", "expiry", "action", "params"})),
    ("B-01", "parameter binding removed", _approval_off({"params"})),
    ("B-01", "single use removed", _approval_off({"status"})),
    ("B-02", "expiry removed", _approval_off({"expiry"})),
    ("B-03", "rejected status ignored", _approval_off({"status"})),
    ("B-04", "pending status ignored", _approval_off({"status"})),
    ("B-05", "all enforcement disabled", lambda m: disable_enforcement(m)),
    ("B-06", "approval never marked used", lambda m: m.setattr(ApprovalService, "mark_used", lambda self, rid: None)),
]


@pytest.mark.parametrize("case_id, what, switch_off", B_MUTATIONS, ids=[f"{c}-{w}" for c, w, _ in B_MUTATIONS])
def test_governance_trajectory_case_fails_when_its_control_is_removed(monkeypatch, case_id, what, switch_off):
    assert trajectory.evaluate_case(B_CASES[case_id])["result"] == "PASS"
    with monkeypatch.context() as m:
        switch_off(m)
        assert trajectory.evaluate_case(B_CASES[case_id])["result"] == "FAIL", f"{case_id} did not notice: {what}"
    assert trajectory.evaluate_case(B_CASES[case_id])["result"] == "PASS"  # and the control is back afterwards
