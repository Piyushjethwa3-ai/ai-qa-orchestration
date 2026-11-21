"""Day 6: the permission matrix and the approval service (BR06, BR07)."""

import pytest
from day6_support import (APPROVER, EMPLOYEE_A, EMPLOYEE_B, RESET_PARAMS, Clock, _offline_and_isolated,  # noqa: F401
                          clock)

from app.agent.tools import ToolBackend
from app.governance import permissions, privileged
from app.governance.approvals import ApprovalError, ApprovalService, validate_action

APPROVERS = {APPROVER: {}, "APR002": {}}


def _service(clock, ttl=900):
    return ApprovalService(approvers=APPROVERS, clock=clock, ttl_seconds=ttl)


def _code(callable_, *args):
    with pytest.raises(ApprovalError) as exc:
        callable_(*args)
    return exc.value.code


# -- permission matrix -----------------------------------------------------------------------------------
def test_unknown_tools_roles_and_always_prohibited_operations_are_denied():
    assert permissions.classify("agent", "delete_everything") == permissions.PROHIBITED
    assert permissions.classify("stranger", "get_ticket") == permissions.PROHIBITED
    for tool in permissions.ALWAYS_PROHIBITED:
        for role in permissions.ROLES:
            assert permissions.classify(role, tool) == permissions.PROHIBITED


@pytest.mark.parametrize("tool, expected", [
    ("get_service_status", "ALLOWED"), ("retrieve_guide", "ALLOWED"), ("search_tickets", "ALLOWED"),
    ("get_ticket", "ALLOWED"), ("get_privileged_request_status", "ALLOWED"),
    ("create_ticket", "CONFIRMATION_REQUIRED"), ("request_privileged_action", "CONFIRMATION_REQUIRED"),
    ("execute_privileged_action", "APPROVAL_REQUIRED"),
])
def test_employee_and_agent_have_identical_permissions(tool, expected):
    assert permissions.classify("employee", tool) == permissions.classify("agent", tool) == expected


def test_only_an_it_approver_may_decide_approvals_or_read_the_audit_log():
    for tool in ("decide_approval", "read_audit_log"):
        assert permissions.classify("it_approver", tool) == permissions.ALLOWED
        assert permissions.classify("employee", tool) == permissions.classify("agent", tool) == permissions.PROHIBITED


def test_an_approver_cannot_use_employee_tools_so_approving_is_not_executing():
    for tool in ("create_ticket", "request_privileged_action", "execute_privileged_action", "get_ticket"):
        assert permissions.classify("it_approver", tool) == permissions.PROHIBITED


def test_every_registered_tool_is_in_the_matrix_with_an_allowed_parameter_list():
    backend = ToolBackend(tickets=[])
    privileged.install(backend, ApprovalService(approvers=APPROVERS))
    for tool in backend.tool_names:
        assert tool in permissions.MATRIX, f"{tool} would be reachable without a permission decision"
        assert tool in permissions.PARAM_KEYS


# -- approval service ------------------------------------------------------------------------------------
def test_request_starts_pending_and_cannot_execute_until_approved(clock):
    svc = _service(clock)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    assert svc.get(rid)["status"] == "PENDING"
    assert _code(svc.check_execution, EMPLOYEE_A, rid, "password_reset", RESET_PARAMS) == "pending"


def test_approved_request_executes_once_only(clock):
    svc = _service(clock)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    svc.decide(APPROVER, rid, "approve", "checked")
    assert svc.check_execution(EMPLOYEE_A, rid, "password_reset", RESET_PARAMS)["status"] == "APPROVED"
    svc.mark_used(rid)
    assert _code(svc.check_execution, EMPLOYEE_A, rid, "password_reset", RESET_PARAMS) == "already_used"
    assert svc.display_status(rid) == "USED"


def test_rejected_request_can_never_execute_or_be_reapproved(clock):
    svc = _service(clock)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    svc.decide(APPROVER, rid, "reject", "not verified")
    assert _code(svc.check_execution, EMPLOYEE_A, rid, "password_reset", RESET_PARAMS) == "rejected"
    assert _code(svc.decide, "APR002", rid, "approve") == "already_decided"


@pytest.mark.parametrize("employee, action, params, code", [
    (EMPLOYEE_B, "password_reset", RESET_PARAMS, "wrong_employee"),                                  # replay for another employee
    (EMPLOYEE_A, "software_access_grant", {"target_employee_id": EMPLOYEE_A, "application": "x"}, "action_mismatch"),
    (EMPLOYEE_A, "password_reset", {"target_employee_id": EMPLOYEE_B}, "params_changed"),            # changed parameters
])
def test_approval_applies_only_to_the_approved_employee_action_and_parameters(clock, employee, action, params, code):
    svc = _service(clock)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    svc.decide(APPROVER, rid, "approve")
    assert _code(svc.check_execution, employee, rid, action, params) == code
    assert svc.get(rid)["status"] == "APPROVED"  # a refused attempt does not burn the approval


def test_approval_is_bound_to_the_request_id(clock):
    svc = _service(clock)
    first = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    second = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    svc.decide(APPROVER, first, "approve")
    assert svc.check_execution(EMPLOYEE_A, first, "password_reset", RESET_PARAMS)
    assert _code(svc.check_execution, EMPLOYEE_A, second, "password_reset", RESET_PARAMS) == "pending"
    assert _code(svc.check_execution, EMPLOYEE_A, "PRV-9999", "password_reset", RESET_PARAMS) == "unknown_request"
    assert svc.get(first)["binding"] != svc.get(second)["binding"]


def test_approval_expires(clock):
    svc = _service(clock, ttl=60)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    svc.decide(APPROVER, rid, "approve")
    clock.advance(61)
    assert _code(svc.check_execution, EMPLOYEE_A, rid, "password_reset", RESET_PARAMS) == "expired"
    assert svc.display_status(rid) == "EXPIRED"


def test_only_known_approvers_decide_and_nobody_approves_their_own_request(clock):
    svc = _service(clock)
    rid = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    for impostor in (EMPLOYEE_A, EMPLOYEE_B, "", "apr001", "ADMIN"):
        assert _code(svc.decide, impostor, rid, "approve") == "not_an_approver"
    assert svc.get(rid)["status"] == "PENDING"
    self_svc = ApprovalService(approvers={EMPLOYEE_A: {}}, clock=clock)
    own = self_svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS)["request_id"]
    assert _code(self_svc.decide, EMPLOYEE_A, own, "approve") == "self_approval"
    assert _code(svc.decide, APPROVER, rid, "maybe") == "invalid_decision"
    assert _code(svc.decide, APPROVER, "PRV-9999", "approve") == "unknown_request"


def test_request_creation_is_idempotent_by_key(clock):
    svc = _service(clock)
    first = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS, idempotency_key="k")
    again = svc.create_request(EMPLOYEE_A, "password_reset", RESET_PARAMS, idempotency_key="k")
    assert first["request_id"] == again["request_id"]
    assert svc.create_request(EMPLOYEE_B, "password_reset", {"target_employee_id": EMPLOYEE_B},
                              idempotency_key="k")["request_id"] != first["request_id"]


@pytest.mark.parametrize("action, params", [
    ("format_disk", {"target_employee_id": "EMP001"}),
    ("password_reset", {}),
    ("password_reset", {"target_employee_id": "EMP001", "extra": "x"}),
    ("password_reset", {"target_employee_id": ""}),
    ("software_access_grant", {"target_employee_id": "EMP001"}),
    ("password_reset", "EMP001"),
])
def test_invalid_privileged_requests_are_rejected(action, params):
    with pytest.raises(ApprovalError) as exc:
        validate_action(action, params)
    assert exc.value.code == "invalid_request"
