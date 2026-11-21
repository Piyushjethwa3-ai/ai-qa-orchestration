"""
Day 6 regression: a caller cannot tell whether a privileged request ID exists.

Before this fix, asking about (or trying to execute) ANOTHER employee's request was refused with different wording and
a different status from a request that does not exist. Because request IDs are sequential (PRV-0001, PRV-0002 ...), an
attacker could walk the IDs and learn which exist. Now both cases return the SAME response, in every state the real
request can be in. The precise reason is kept in the approver-only audit log, so an investigator still sees the truth.
(Confirmation IDs have the same pattern and are NOT covered by this fix; see the README limitations.)
"""

import json

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, FIXED_AUDIT_TIME, Clock, _offline_and_isolated, confirmed,  # noqa: F401
                          ctx, execute, submit_reset)
from fastapi.testclient import TestClient

from app import runtime
from app.agent.tools import ToolResult
from app.governance import privileged
from app.governance.stack import build_governed_stack
from app.main import app

STATES = ["pending", "approved", "rejected", "used", "expired"]
MISSING = "PRV-9999"
WEIRD_IDS = ["", None, 123, "../PRV-0001", "prv-0001", "PRV-0001 ", "x" * 500]
LEAKING_WORDS = ("wrong_employee", "unknown_request", "not your request")


def shape(result: ToolResult) -> tuple:
    """Everything a caller can see (the internal reason is deliberately NOT part of what callers see)."""
    return (result.tool, result.status, json.dumps(result.data, sort_keys=True), result.error, result.retryable)


def build(state: str):
    clock = Clock()
    stack = build_governed_stack(tickets=None, clock=clock, audit_clock=lambda: FIXED_AUDIT_TIME)
    rid = submit_reset(stack)  # EMP001's request: PRV-0001
    if state in ("approved", "used", "expired"):
        stack.gateway.decide_approval(APPROVER, rid, "approve", "identity verified by phone")
    if state == "rejected":
        stack.gateway.decide_approval(APPROVER, rid, "reject", "could not verify")
    if state == "used":
        assert execute(stack, rid, key="first").status == "SUCCESS"
    if state == "expired":
        clock.advance(901)
    return stack, rid


def status_of(stack, employee, request_id):
    return stack.gateway.invoke(ctx(employee), "get_privileged_request_status", {"request_id": request_id})


def try_execute(stack, employee, request_id):
    params = {"request_id": request_id, "action": "password_reset", "action_params": {"target_employee_id": EMPLOYEE_A}}
    cid = confirmed(stack, employee, "execute_privileged_action", params)
    return stack.gateway.invoke(ctx(employee), "execute_privileged_action",
                                {**params, "confirmation_id": cid, "idempotency_key": f"probe-{employee}-{request_id}"})


# -- the gateway and tools ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("state", STATES)
def test_reading_someone_elses_request_is_identical_to_reading_a_missing_one(state):
    stack, rid = build(state)
    foreign, missing = status_of(stack, EMPLOYEE_B, rid), status_of(stack, EMPLOYEE_B, MISSING)
    assert shape(foreign) == shape(missing)
    assert foreign.status == "NOT_FOUND" and foreign.error == "request not found" and foreign.data == {}


@pytest.mark.parametrize("state", STATES)
def test_executing_someone_elses_request_is_identical_to_executing_a_missing_one(state):
    stack, rid = build(state)
    executions_before = dict(stack.extras["executions"])
    foreign, missing = try_execute(stack, EMPLOYEE_B, rid), try_execute(stack, EMPLOYEE_B, MISSING)
    assert shape(foreign) == shape(missing)
    assert foreign.status == "DENIED" and foreign.error == "approval not valid (not found)" and foreign.data == {}
    assert stack.extras["executions"] == executions_before  # and nothing ran


@pytest.mark.parametrize("bad_id", WEIRD_IDS, ids=repr)
def test_malformed_ids_look_the_same_as_missing_ones(bad_id):
    stack, rid = build("approved")
    assert shape(status_of(stack, EMPLOYEE_B, bad_id)) == shape(status_of(stack, EMPLOYEE_B, MISSING))
    assert shape(status_of(stack, EMPLOYEE_A, bad_id)) == shape(status_of(stack, EMPLOYEE_A, MISSING))  # even for the owner


def test_the_state_of_someone_elses_request_never_shows():
    shapes = set()
    for state in STATES:
        stack, rid = build(state)
        shapes.add((shape(status_of(stack, EMPLOYEE_B, rid)), shape(try_execute(stack, EMPLOYEE_B, rid))))
    assert len(shapes) == 1, "a non-owner can tell the state of someone else's request apart"


def test_the_owner_still_gets_the_specific_reason():
    """The fix must not make owners' lives harder: the reasons that only an owner can ever see are unchanged."""
    for state, reason in (("pending", "pending"), ("rejected", "rejected"), ("used", "already_used"), ("expired", "expired")):
        stack, rid = build(state)
        assert f"({reason})" in try_execute(stack, EMPLOYEE_A, rid).error, state
        assert status_of(stack, EMPLOYEE_A, rid).status == "SUCCESS"
    stack, rid = build("approved")
    assert status_of(stack, EMPLOYEE_A, rid).data["approval_status"] == "APPROVED"
    assert try_execute(stack, EMPLOYEE_A, "PRV-9999").error == "approval not valid (not found)"  # a typo reads the same


def test_a_guessed_id_gives_the_attacker_nothing_and_changes_nothing():
    stack, rid = build("approved")  # sequential IDs are guessable; the guess must be useless
    before = (stack.extras["approvals"].get(rid), dict(stack.extras["executions"]))
    assert rid == "PRV-0001"
    for _ in range(3):
        try_execute(stack, EMPLOYEE_B, rid)
        status_of(stack, EMPLOYEE_B, rid)
    assert (stack.extras["approvals"].get(rid), dict(stack.extras["executions"])) == before


# -- the audit log keeps the truth, callers never see it ---------------------------------------------------------------------
def test_the_audit_log_keeps_the_precise_reason_for_an_investigator():
    stack, rid = build("approved")
    status_of(stack, EMPLOYEE_B, rid)
    try_execute(stack, EMPLOYEE_B, rid)
    status_of(stack, EMPLOYEE_B, MISSING)
    try_execute(stack, EMPLOYEE_B, MISSING)
    records = [r for r in stack.gateway.read_audit(APPROVER) if r["actor_id"] == EMPLOYEE_B]
    reasons = [r["error"] for r in records]
    assert reasons == ["not your request", "approval not valid (wrong_employee)",
                       "request not found", "approval not valid (unknown_request)"]
    assert all(r["result_status"] in ("NOT_FOUND", "DENIED") for r in records)
    assert stack.extras["audit"].verify_chain() == (True, None)


def test_the_precise_reason_never_reaches_a_caller_over_the_gateway_the_agent_or_the_cli():
    import io

    from app.agent import cli
    stack, rid = build("approved")
    outputs = [repr(status_of(stack, EMPLOYEE_B, rid).error), repr(try_execute(stack, EMPLOYEE_B, rid).error)]
    # the agent path: a planner that probes the request, as a model might be told to
    from app.agent.planner import Reply, ToolCall

    probes = [ToolCall("get_privileged_request_status", {"request_id": rid}),
              ToolCall("execute_privileged_action", {"request_id": rid, "action": "password_reset",
                                                     "action_params": {"target_employee_id": EMPLOYEE_A},
                                                     "confirmation_id": "CONF-9999", "idempotency_key": "p"})]

    class Prober:
        def plan(self, turn):
            return probes[len(turn.observations)] if len(turn.observations) < len(probes) else Reply(
                "ESCALATED", "done", escalation_reason="probe")

    stack.runner.planner = Prober()
    outputs.append(json.dumps(stack.runner.handle(EMPLOYEE_B, "S9", "probe").to_dict()))
    for governed, name in ((True, "privileged"), (True, "cross-user"), (True, "no-confirmation")):
        out = io.StringIO()
        cli.main(["demo", name], governed=governed, out=out)
        outputs.append(out.getvalue())
    text = "\n".join(outputs)
    assert not [w for w in LEAKING_WORDS if w in text], "an internal reason reached a caller-facing output"


# -- over HTTP ---------------------------------------------------------------------------------------------------------------
def _api_case(state):
    runtime.reset_services(tickets=None, clock=Clock(), audit_clock=lambda: FIXED_AUDIT_TIME)
    api = TestClient(app)
    e1, apr = {"X-Demo-Employee-ID": EMPLOYEE_A}, {"X-Demo-Approver-ID": APPROVER}
    api.post("/agent/chat", json={"session_id": "s", "message": "I forgot my password and need a reset"}, headers=e1)
    api.post("/agent/chat", json={"session_id": "s", "message": "yes"}, headers=e1)
    if state in ("approved", "used"):
        api.post("/approvals/PRV-0001/decision", json={"decision": "approve"}, headers=apr)
    if state == "rejected":
        api.post("/approvals/PRV-0001/decision", json={"decision": "reject"}, headers=apr)
    if state == "used":
        ap = {"target_employee_id": EMPLOYEE_A}
        cid = _api_confirm(api, e1, "PRV-0001", ap)
        done = api.post("/tools/execute_privileged_action", headers=e1, json={"params": {
            "request_id": "PRV-0001", "action": "password_reset", "action_params": ap, "confirmation_id": cid,
            "idempotency_key": "first"}})
        assert done.status_code == 200
    return api, apr


def _api_confirm(api, headers, request_id, action_params):
    cid = api.post("/confirmations", headers=headers, json={"action": "execute_privileged_action", "params": {
        "request_id": request_id, "action": "password_reset", "action_params": action_params}}).json()["confirmation_id"]
    assert api.post(f"/confirmations/{cid}/confirm", headers=headers).status_code == 200
    return cid


@pytest.mark.parametrize("state", ["pending", "approved", "rejected", "used"])
def test_over_http_a_foreign_request_and_a_missing_one_return_identical_responses(state):
    try:
        api, _ = _api_case(state)
        e2 = {"X-Demo-Employee-ID": EMPLOYEE_B}
        ap = {"target_employee_id": EMPLOYEE_A}

        def read(rid):
            return api.post("/tools/get_privileged_request_status", headers=e2, json={"params": {"request_id": rid}})

        def run(rid):
            cid = _api_confirm(api, e2, rid, ap)
            return api.post("/tools/execute_privileged_action", headers=e2, json={"params": {
                "request_id": rid, "action": "password_reset", "action_params": ap, "confirmation_id": cid,
                "idempotency_key": f"probe-{rid}"}})

        for call in (read, run):
            foreign, missing = call("PRV-0001"), call(MISSING)
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
            assert not [w for w in LEAKING_WORDS if w in foreign.text]
        assert read("PRV-0001").status_code == 404 and run("PRV-0001").status_code == 403
    finally:
        runtime.reset_services()


def test_over_http_only_an_approver_can_read_the_precise_reason():
    try:
        api, apr = _api_case("approved")
        e2 = {"X-Demo-Employee-ID": EMPLOYEE_B}
        api.post("/tools/get_privileged_request_status", headers=e2, json={"params": {"request_id": "PRV-0001"}})
        assert api.get("/audit", headers=e2).status_code == 403
        records = api.get("/audit", headers=apr).json()["records"]
        assert any(r["error"] == "not your request" and r["actor_id"] == EMPLOYEE_B for r in records)
    finally:
        runtime.reset_services()


# -- would this test notice a regression? ---------------------------------------------------------------------------------------
def test_the_comparison_detects_the_old_behaviour_for_status_reads(monkeypatch):
    stack, rid = build("approved")
    assert shape(status_of(stack, EMPLOYEE_B, rid)) == shape(status_of(stack, EMPLOYEE_B, MISSING))
    original = stack.backend._handlers["get_privileged_request_status"]

    def old_behaviour(params):
        record = stack.extras["approvals"].get(params.get("request_id")) if isinstance(params.get("request_id"), str) else None
        if record and record["employee_id"] != params["employee_id"]:
            return ToolResult("get_privileged_request_status", "DENIED", error="not your request")  # what used to happen
        return original(params)

    monkeypatch.setattr(stack.backend, "_handlers", {**stack.backend._handlers, "get_privileged_request_status": old_behaviour})
    assert shape(status_of(stack, EMPLOYEE_B, rid)) != shape(status_of(stack, EMPLOYEE_B, MISSING))


def test_the_comparison_detects_the_old_behaviour_for_execution(monkeypatch):
    stack, rid = build("approved")
    assert shape(try_execute(stack, EMPLOYEE_B, rid)) == shape(try_execute(stack, EMPLOYEE_B, MISSING))
    monkeypatch.setattr(privileged, "HIDDEN_CODES", ())  # remove the masking
    assert shape(try_execute(stack, EMPLOYEE_B, rid)) != shape(try_execute(stack, EMPLOYEE_B, MISSING))
