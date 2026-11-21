"""Week 5 tools and the server-side confirmation store (BR02, BR06, BR08, BR11)."""

import pytest
from agent_support import _offline_and_isolated, data_files_snapshot  # noqa: F401

from app.agent.confirmations import ConfirmationError, ConfirmationStore
from app.agent.tools import (DENIED, FAILED, NOT_FOUND, STATUSES, SUCCESS, TIMEOUT, ToolBackend)

CONTENT = {"subject": "VPN problem", "description": "VPN fails on my Mac"}


def _confirmed(backend, employee="EMP001", session="S1", params=CONTENT, action="create_ticket"):
    cid = backend.confirmations.propose(employee, session, action, params)
    backend.confirmations.confirm(employee, session, cid)
    return cid


def _create(backend, cid, key="S1:k1", employee="EMP001", **overrides):
    return backend.invoke("create_ticket", {"employee_id": employee, **CONTENT, "idempotency_key": key,
                                           "confirmation_id": cid, **overrides})


# -- confirmation store ------------------------------------------------------------------------------
def test_confirmation_lifecycle_and_single_use():
    store = ConfirmationStore()
    cid = store.propose("EMP001", "S1", "create_ticket", CONTENT)
    with pytest.raises(ConfirmationError) as e:
        store.validate("EMP001", "create_ticket", CONTENT, cid)
    assert e.value.code == "not_confirmed"
    store.confirm("EMP001", "S1", cid)
    store.confirm("EMP001", "S1", cid)  # repeating a yes is harmless
    assert store.validate("EMP001", "create_ticket", CONTENT, cid)["status"] == "CONFIRMED"
    store.consume(cid)
    with pytest.raises(ConfirmationError) as e:
        store.validate("EMP001", "create_ticket", CONTENT, cid)
    assert e.value.code == "already_used"


@pytest.mark.parametrize("employee, action, params, code", [
    ("EMP002", "create_ticket", CONTENT, "unknown_confirmation"),  # someone else's looks like a missing one
    ("EMP001", "other_action", CONTENT, "action_mismatch"),
    ("EMP001", "create_ticket", {**CONTENT, "subject": "changed"}, "params_changed"),
])
def test_confirmation_is_bound_to_employee_action_and_parameters(employee, action, params, code):
    store = ConfirmationStore()
    cid = store.propose("EMP001", "S1", "create_ticket", CONTENT)
    store.confirm("EMP001", "S1", cid)
    with pytest.raises(ConfirmationError) as e:
        store.validate(employee, action, params, cid)
    assert e.value.code == code
    assert e.value.internal == ("wrong_employee" if employee == "EMP002" else code)  # the audit log keeps the truth


def test_only_the_owning_employee_and_session_can_confirm_and_cancel_blocks_use():
    store = ConfirmationStore()
    cid = store.propose("EMP001", "S1", "create_ticket", CONTENT)
    for employee, session in (("EMP002", "S1"), ("EMP001", "S2")):
        with pytest.raises(ConfirmationError) as e:
            store.confirm(employee, session, cid)
        assert e.value.code == "unknown_confirmation" and e.value.internal == "wrong_employee"  # callers see "unknown"
    store.cancel(cid)
    with pytest.raises(ConfirmationError):
        store.validate("EMP001", "create_ticket", CONTENT, cid)
    with pytest.raises(ConfirmationError):
        store.confirm("EMP001", "S1", "CONF-9999")


# -- reads --------------------------------------------------------------------------------------------
def test_service_status_default_and_distinct_failure_statuses():
    backend = ToolBackend()
    ok = backend.invoke("get_service_status", {"service": "vpn"})
    assert ok.status == SUCCESS and ok.confirmed and ok.data["status"] in ("operational", "degraded", "outage")
    assert backend.invoke("get_service_status", {"service": "printer"}).status == NOT_FOUND
    assert backend.invoke("get_service_status", {}).status == FAILED
    assert backend.invoke("no_such_tool", {}).status == FAILED
    bad = ToolBackend(status_fixtures={"vpn": {"service": "vpn", "status": "maybe", "updated_at": "x"}})
    assert bad.invoke("get_service_status", {"service": "vpn"}).status == FAILED
    assert set(STATUSES) >= {SUCCESS, FAILED, TIMEOUT, DENIED, NOT_FOUND, "PENDING_APPROVAL"}


def test_ticket_reads_are_limited_to_the_owner():
    backend = ToolBackend()
    own = backend.invoke("search_tickets", {"employee_id": "EMP001"}).data["tickets"]
    assert {t["ticket_id"] for t in own} == {"TCK-1001", "TCK-1005"}
    assert backend.invoke("get_ticket", {"employee_id": "EMP001", "ticket_id": "tck-1001"}).status == SUCCESS
    denied = backend.invoke("get_ticket", {"employee_id": "EMP002", "ticket_id": "TCK-1001"})
    assert denied.status == DENIED and denied.data == {}  # no ticket content in a denial
    assert "VPN client" not in repr(denied)
    assert backend.invoke("get_ticket", {"employee_id": "EMP001", "ticket_id": "TCK-9999"}).status == NOT_FOUND


def test_retrieve_guide_uses_approved_documents_only_and_flags_text_as_untrusted():
    result = ToolBackend().invoke("retrieve_guide", {"query": "vpn password change", "os": "macos"})
    docs = result.data["documents"]
    assert result.status == SUCCESS and result.data["untrusted_text"] is True
    assert docs and all(d["status"] == "approved" for d in docs)
    assert "KB-VPN-MAC-CURRENT" in [d["doc_id"] for d in docs]
    assert not any(d["doc_id"].endswith("-OLD") or d["os"] == "windows" for d in docs)
    assert docs[0]["sections"]  # parsed into headings and lines


# -- writes -------------------------------------------------------------------------------------------
def test_create_ticket_requires_a_matching_recorded_confirmation():
    backend = ToolBackend(tickets=[])
    for cid in (None, "CONF-9999"):
        assert _create(backend, cid).status == DENIED
    proposed_only = backend.confirmations.propose("EMP001", "S1", "create_ticket", CONTENT)
    assert _create(backend, proposed_only).status == DENIED
    other = _confirmed(backend, employee="EMP002")
    assert _create(backend, other).status == DENIED  # someone else's confirmation
    changed = _confirmed(backend)
    assert _create(backend, changed, subject="a different subject").status == DENIED  # parameters changed
    assert backend.tickets == []  # nothing was written by any refused call


def test_create_ticket_success_writes_memory_only_and_consumes_the_confirmation():
    before = data_files_snapshot()
    backend = ToolBackend(tickets=[])
    cid = _confirmed(backend)
    result = _create(backend, cid)
    assert result.status == SUCCESS and result.confirmed and result.data["replayed"] is False
    assert result.data["ticket"]["ticket_id"] == "TCK-1001" and len(backend.tickets) == 1
    assert backend.confirmations.get(cid)["status"] == "CONSUMED"
    assert data_files_snapshot() == before  # data/*.json is never written


def test_same_idempotency_key_never_creates_a_second_ticket():
    backend = ToolBackend(tickets=[])
    cid = _confirmed(backend)
    first, again = _create(backend, cid), _create(backend, cid)
    assert again.status == SUCCESS and again.data["replayed"] is True
    assert again.data["ticket"]["ticket_id"] == first.data["ticket"]["ticket_id"]
    assert len(backend.tickets) == 1


def test_idempotency_key_reused_with_different_content_is_refused():
    backend = ToolBackend(tickets=[])
    _create(backend, _confirmed(backend))
    clash = _create(backend, _confirmed(backend), subject="Other")  # confirmation covers the original content only
    assert clash.status in (FAILED, DENIED) and len(backend.tickets) == 1


def test_ticket_numbers_continue_after_existing_tickets():
    backend = ToolBackend()  # six seeded tickets
    result = _create(backend, _confirmed(backend))
    assert result.data["ticket"]["ticket_id"] == "TCK-1007"


# -- fault scripting ----------------------------------------------------------------------------------
def test_timeout_after_success_really_writes_but_reports_timeout():
    backend = ToolBackend(tickets=[])
    backend.script_faults("create_ticket", ["timeout_after_success"])
    cid = _confirmed(backend)
    result = _create(backend, cid)
    assert result.status == TIMEOUT and result.retryable and not result.confirmed
    assert len(backend.tickets) == 1  # the write happened although the caller saw a timeout


def test_timeout_before_and_error_do_not_write_and_faults_are_consumed_in_order():
    backend = ToolBackend(tickets=[])
    backend.script_faults("create_ticket", ["timeout_before", "error", "ok"])
    cid = _confirmed(backend)
    assert [_create(backend, cid).status for _ in range(3)] == [TIMEOUT, FAILED, SUCCESS]
    assert len(backend.tickets) == 1


def test_unknown_fault_outcome_is_rejected():
    with pytest.raises(ValueError):
        ToolBackend().script_faults("create_ticket", ["explode"])
