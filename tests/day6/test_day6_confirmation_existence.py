"""
Day 6 regression: a caller cannot tell whether a confirmation ID exists.

Before this fix, trying to confirm (or use) ANOTHER employee's confirmation was refused differently from a confirmation
that does not exist: HTTP 403 versus 404 on `/confirmations/{id}/confirm`, and `wrong_employee` versus
`unknown_confirmation` in a tool refusal. Confirmation IDs are sequential (CONF-0001 ...), so an attacker could walk
them and learn which exist. Now both cases are indistinguishable to the caller, in every state the real confirmation
can be in. The precise reason is kept in the approver-only audit log. The owner's own behaviour is unchanged.
"""

import json

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, FIXED_AUDIT_TIME, Clock, _offline_and_isolated, ctx)  # noqa: F401
from fastapi.testclient import TestClient

from app import runtime
from app.agent.confirmations import ConfirmationError, ConfirmationStore
from app.agent.tools import ToolResult
from app.governance.stack import build_governed_stack
from app.main import app

STATES = ["proposed", "confirmed", "consumed", "cancelled"]
MISSING = "CONF-9999"
TICKET = {"subject": "VPN problem", "description": "VPN fails"}
SECRET_WORDS = ("wrong_employee",)


def make_confirmation(store: ConfirmationStore, state: str, employee=EMPLOYEE_A, action="create_ticket", params=TICKET) -> str:
    cid = store.propose(employee, "direct-api", action, params)
    if state in ("confirmed", "consumed"):
        store.confirm(employee, "direct-api", cid)
    if state == "consumed":
        store.consume(cid)
    if state == "cancelled":
        store.cancel(cid)
    return cid


def caught(call) -> tuple:
    """What a caller learns from a refusal: the exception type, code and message (NOT the internal reason)."""
    try:
        call()
    except ConfirmationError as exc:
        return ("refused", exc.code, str(exc))
    return ("accepted",)


def shape(result: ToolResult) -> tuple:
    return (result.tool, result.status, json.dumps(result.data, sort_keys=True), result.error, result.retryable)


def new_stack():
    return build_governed_stack(tickets=None, clock=Clock(), audit_clock=lambda: FIXED_AUDIT_TIME)


# -- the store -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("state", STATES)
def test_confirming_someone_elses_confirmation_looks_exactly_like_confirming_a_missing_one(state):
    store = ConfirmationStore()
    cid = make_confirmation(store, state)
    foreign = caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", cid))
    assert foreign == caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", MISSING)) == ("refused", "unknown_confirmation", "unknown_confirmation")


@pytest.mark.parametrize("state", STATES)
def test_using_someone_elses_confirmation_looks_exactly_like_using_a_missing_one(state):
    store = ConfirmationStore()
    cid = make_confirmation(store, state)
    foreign = caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, cid))
    assert foreign == caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, MISSING))
    assert foreign == ("refused", "unknown_confirmation", "unknown_confirmation")


def test_the_store_keeps_the_precise_internal_reason_for_the_audit_log():
    store = ConfirmationStore()
    cid = make_confirmation(store, "confirmed")
    with pytest.raises(ConfirmationError) as foreign:
        store.validate(EMPLOYEE_B, "create_ticket", TICKET, cid)
    with pytest.raises(ConfirmationError) as missing:
        store.validate(EMPLOYEE_B, "create_ticket", TICKET, MISSING)
    assert (foreign.value.code, foreign.value.internal) == ("unknown_confirmation", "wrong_employee")
    assert (missing.value.code, missing.value.internal) == ("unknown_confirmation", "unknown_confirmation")


@pytest.mark.parametrize("bad", ["", None, 123, "conf-0001", "CONF-0001 ", "x" * 300])
def test_malformed_ids_look_like_missing_ones(bad):
    store = ConfirmationStore()
    make_confirmation(store, "confirmed")
    assert caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, bad)) == \
        caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, MISSING))


def test_the_owner_keeps_every_specific_reason_and_ownership_is_still_enforced():
    store = ConfirmationStore()
    expected = {"proposed": "not_confirmed", "consumed": "already_used", "cancelled": "cancelled"}
    for state, reason in expected.items():
        cid = make_confirmation(store, state)
        assert caught(lambda: store.validate(EMPLOYEE_A, "create_ticket", TICKET, cid)) == ("refused", reason, reason)
    cid = make_confirmation(store, "confirmed")
    assert caught(lambda: store.validate(EMPLOYEE_A, "other_action", TICKET, cid))[1] == "action_mismatch"
    assert caught(lambda: store.validate(EMPLOYEE_A, "create_ticket", {**TICKET, "subject": "x"}, cid))[1] == "params_changed"
    assert caught(lambda: store.validate(EMPLOYEE_A, "create_ticket", TICKET, cid)) == ("accepted",)
    assert caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, cid))[1] == "unknown_confirmation"  # still refused


def test_a_confirmation_from_another_session_looks_missing_to_its_own_employee_too():
    store = ConfirmationStore()
    cid = store.propose(EMPLOYEE_A, "session-1", "create_ticket", TICKET)
    assert caught(lambda: store.confirm(EMPLOYEE_A, "session-2", cid)) == caught(lambda: store.confirm(EMPLOYEE_A, "session-2", MISSING))
    store.confirm(EMPLOYEE_A, "session-1", cid)  # and it still works in its own session


# -- the gateway and tools ---------------------------------------------------------------------------------------------------------
def _calls(stack, employee, cid):
    """The three tools that consume a confirmation, called by `employee` with confirmation `cid`."""
    return {
        "create_ticket": stack.gateway.invoke(ctx(employee), "create_ticket", {**TICKET, "idempotency_key": f"k-{employee}", "confirmation_id": cid}),
        "request_privileged_action": stack.gateway.invoke(ctx(employee), "request_privileged_action", {
            "action": "password_reset", "target_employee_id": employee, "idempotency_key": f"r-{employee}", "confirmation_id": cid}),
        "execute_privileged_action": stack.gateway.invoke(ctx(employee), "execute_privileged_action", {
            "request_id": "PRV-9999", "action": "password_reset", "action_params": {"target_employee_id": employee},
            "idempotency_key": f"x-{employee}", "confirmation_id": cid}),
    }


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("action", ["create_ticket", "request_privileged_action", "execute_privileged_action"])
def test_every_tool_gives_the_same_refusal_for_someone_elses_confirmation_as_for_a_missing_one(state, action):
    stack = new_stack()
    cid = make_confirmation(stack.confirmations, state, action=action, params=TICKET)
    foreign, missing = _calls(stack, EMPLOYEE_B, cid)[action], _calls(stack, EMPLOYEE_B, MISSING)[action]
    assert shape(foreign) == shape(missing)
    assert foreign.status == "DENIED" and foreign.error == "confirmation required (unknown_confirmation)" and foreign.data == {}
    assert len(stack.backend.tickets) == 6 and stack.extras["executions"] == {}  # nothing was written


def test_someone_elses_confirmation_cannot_be_used_and_the_owner_still_can():
    stack = new_stack()
    cid = make_confirmation(stack.confirmations, "confirmed")
    assert _calls(stack, EMPLOYEE_B, cid)["create_ticket"].status == "DENIED"
    assert len(stack.backend.tickets) == 6
    mine = stack.gateway.invoke(ctx(EMPLOYEE_A), "create_ticket", {**TICKET, "idempotency_key": "k", "confirmation_id": cid})
    assert mine.status == "SUCCESS" and len(stack.backend.tickets) == 7  # valid confirmation behaviour is preserved


def test_the_audit_log_keeps_the_precise_reason_and_callers_never_see_it():
    stack = new_stack()
    cid = make_confirmation(stack.confirmations, "confirmed")
    outputs = []
    for tool, call in _calls(stack, EMPLOYEE_B, cid).items():
        outputs.append(repr(call.error))
    for tool, call in _calls(stack, EMPLOYEE_B, MISSING).items():
        outputs.append(repr(call.error))
    records = [r for r in stack.gateway.read_audit(APPROVER) if r["actor_id"] == EMPLOYEE_B and r["tool"] != "read_audit_log"]
    reasons = [(r["tool"], r["error"]) for r in records]
    assert reasons == [("create_ticket", "confirmation required (wrong_employee)"),
                       ("request_privileged_action", "confirmation required (wrong_employee)"),
                       ("execute_privileged_action", "confirmation required (wrong_employee)"),
                       ("create_ticket", "confirmation required (unknown_confirmation)"),
                       ("request_privileged_action", "confirmation required (unknown_confirmation)"),
                       ("execute_privileged_action", "confirmation required (unknown_confirmation)")]
    assert stack.extras["audit"].verify_chain() == (True, None)
    assert not [w for w in SECRET_WORDS if w in " ".join(outputs)]


def test_the_agent_trace_and_the_cli_never_show_the_precise_reason():
    import io

    from app.agent import cli
    from app.agent.planner import Reply, ToolCall

    stack = new_stack()
    cid = make_confirmation(stack.confirmations, "confirmed")
    attempts = [ToolCall("create_ticket", {**TICKET, "idempotency_key": "p", "confirmation_id": cid})]

    class Prober:
        def plan(self, turn):
            return attempts[0] if not turn.observations else Reply("ESCALATED", "done", escalation_reason="probe")

    stack.runner.planner = Prober()
    trace = json.dumps(stack.runner.handle(EMPLOYEE_B, "S9", "probe").to_dict())
    out = io.StringIO()
    for name in ("no-confirmation", "privileged", "cross-user"):
        cli.main(["demo", name], governed=True, out=out)
    assert "unknown_confirmation" in trace and not [w for w in SECRET_WORDS if w in trace + out.getvalue()]


# -- over HTTP -------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def api():
    stack = runtime.reset_services(tickets=None, clock=Clock(), audit_clock=lambda: FIXED_AUDIT_TIME)
    yield TestClient(app), stack
    runtime.reset_services()


def hdr(employee):
    return {"X-Demo-Employee-ID": employee}


@pytest.mark.parametrize("state", STATES)
def test_over_http_confirming_someone_elses_confirmation_is_identical_to_a_missing_one(api, state):
    client, stack = api
    cid = make_confirmation(stack.confirmations, state)
    foreign = client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_B))
    missing = client.post(f"/confirmations/{MISSING}/confirm", headers=hdr(EMPLOYEE_B))
    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (404, {"detail": "unknown_confirmation"})
    assert not [w for w in SECRET_WORDS if w in foreign.text]
    assert stack.confirmations.get(cid)["status"] == {"proposed": "PROPOSED", "confirmed": "CONFIRMED", "consumed": "CONSUMED",
                                                      "cancelled": "CANCELLED"}[state]  # the attempt changed nothing


@pytest.mark.parametrize("state", STATES)
def test_over_http_using_someone_elses_confirmation_is_identical_to_using_a_missing_one(api, state):
    client, stack = api
    cid = make_confirmation(stack.confirmations, state)

    def use(confirmation_id):
        return client.post("/tools/create_ticket", headers=hdr(EMPLOYEE_B), json={"params": {
            **TICKET, "idempotency_key": "probe", "confirmation_id": confirmation_id}})

    foreign, missing = use(cid), use(MISSING)
    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
    assert foreign.status_code == 403 and "unknown_confirmation" in foreign.json()["error"]
    assert not [w for w in SECRET_WORDS if w in foreign.text]
    assert len(stack.backend.tickets) == 6


def test_over_http_the_owner_keeps_working_and_keeps_the_specific_reasons(api):
    client, stack = api
    proposed = client.post("/confirmations", headers=hdr(EMPLOYEE_A), json={"action": "create_ticket", "params": TICKET}).json()
    cid = proposed["confirmation_id"]
    assert client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_A)).status_code == 200
    assert client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_A)).status_code == 200  # a repeated yes is harmless
    made = client.post("/tools/create_ticket", headers=hdr(EMPLOYEE_A), json={"params": {
        **TICKET, "idempotency_key": "k1", "confirmation_id": cid}})
    assert made.status_code == 200 and made.json()["data"]["ticket"]["ticket_id"] == "TCK-1007"
    again = client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_A))  # the owner learns it was used
    assert again.status_code == 403 and again.json() == {"detail": "already_used"}


def test_over_http_the_precise_reason_is_in_the_audit_log_for_approvers_only(api):
    client, stack = api
    cid = make_confirmation(stack.confirmations, "confirmed")
    client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_B))      # someone else's
    client.post(f"/confirmations/{MISSING}/confirm", headers=hdr(EMPLOYEE_B))  # missing
    client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_A))      # the owner
    assert client.get("/audit", headers=hdr(EMPLOYEE_B)).status_code == 403
    body = client.get("/audit", headers={"X-Demo-Approver-ID": APPROVER}).json()
    confirms = [(r["actor_id"], r["decision"], r["reason"], r["result_status"]) for r in body["records"]
                if r["tool"] == "confirm_confirmation"]
    assert confirms == [(EMPLOYEE_B, "DENIED", "wrong_employee", None), (EMPLOYEE_B, "DENIED", "unknown_confirmation", None),
                        (EMPLOYEE_A, "ALLOWED", "", "CONFIRMED")]
    assert body["chain_intact"] is True


# -- would these tests notice a regression? ---------------------------------------------------------------------------------------
def _old_confirm(self, employee_id, session_id, confirmation_id):
    """The behaviour before the fix: a non-owner is told the confirmation belongs to someone else."""
    record = self._records.get(confirmation_id)
    if record is None:
        raise ConfirmationError("unknown_confirmation")
    if record["employee_id"] != employee_id or record["session_id"] != session_id:
        raise ConfirmationError("wrong_employee")
    if record["status"] == "CONFIRMED":
        return
    record["status"] = "CONFIRMED"


def _old_validate(original):
    def validate(self, employee_id, action, params, confirmation_id):
        record = self._records.get(confirmation_id) if isinstance(confirmation_id, str) else None
        if record is not None and record["employee_id"] != employee_id:
            raise ConfirmationError("wrong_employee")
        return original(self, employee_id, action, params, confirmation_id)
    return validate


def test_the_comparison_detects_the_old_behaviour_at_the_store(monkeypatch):
    store = ConfirmationStore()
    cid = make_confirmation(store, "confirmed")
    same = (caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", cid)), caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", MISSING)))
    assert same[0] == same[1]
    monkeypatch.setattr(ConfirmationStore, "confirm", _old_confirm)
    monkeypatch.setattr(ConfirmationStore, "validate", _old_validate(ConfirmationStore.validate))
    assert caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", cid)) != caught(lambda: store.confirm(EMPLOYEE_B, "direct-api", MISSING))
    assert caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, cid)) != \
        caught(lambda: store.validate(EMPLOYEE_B, "create_ticket", TICKET, MISSING))


def test_the_comparison_detects_the_old_behaviour_over_http_and_at_the_tools(api, monkeypatch):
    client, stack = api
    cid = make_confirmation(stack.confirmations, "confirmed")
    monkeypatch.setattr(ConfirmationStore, "confirm", _old_confirm)
    monkeypatch.setattr(ConfirmationStore, "validate", _old_validate(ConfirmationStore.validate))
    foreign = client.post(f"/confirmations/{cid}/confirm", headers=hdr(EMPLOYEE_B))
    missing = client.post(f"/confirmations/{MISSING}/confirm", headers=hdr(EMPLOYEE_B))
    assert (foreign.status_code, foreign.json()) != (missing.status_code, missing.json())  # 403 versus 404, as before the fix
    tool_foreign = _calls(stack, EMPLOYEE_B, cid)["create_ticket"]
    tool_missing = _calls(stack, EMPLOYEE_B, MISSING)["create_ticket"]
    assert shape(tool_foreign) != shape(tool_missing)
