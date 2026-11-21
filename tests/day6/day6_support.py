"""
Shared fixtures and helpers for the Day 6 security tests, imported explicitly by each test module.

Deliberately NOT named conftest.py (every conftest.py shares the module name "conftest" and would shadow
the Day 4 helpers; see tests/day5/day5_support.py). Every test is offline and isolated: sockets are
blocked, model variables are removed, the API services are rebuilt for each test, and files go to tmp_path.
"""

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runtime
from app.agent.tools import CallContext
from app.governance.stack import build_governed_stack
from app.main import app

ROOT_DIR = Path(__file__).resolve().parents[2]
EMPLOYEE_A, EMPLOYEE_B, APPROVER = "EMP001", "EMP002", "APR001"
FIXED_AUDIT_TIME = "2026-11-21T00:00:00Z"
RESET_PARAMS = {"target_employee_id": EMPLOYEE_A}


class Clock:
    """A clock tests can move, so approval expiry never needs a real wait."""
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _offline_and_isolated(monkeypatch):
    for variable in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_JUDGE_MODEL", "DAY4_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    def _blocked(*args, **kwargs):
        raise RuntimeError("Network access is disabled in Day 6 tests.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def stack(clock):
    return build_governed_stack(tickets=[], clock=clock, audit_clock=lambda: FIXED_AUDIT_TIME)


@pytest.fixture()
def api(clock):
    runtime.reset_services(tickets=[], clock=clock, audit_clock=lambda: FIXED_AUDIT_TIME)
    yield TestClient(app)
    runtime.reset_services()


def ctx(employee: str = EMPLOYEE_A, role: str = "employee", request_id: str = "T-0001") -> CallContext:
    return CallContext(employee_id=employee, session_id="direct-api", request_id=request_id, role=role)


def confirmed(stack, employee: str, action: str, params: dict) -> str:
    """Record an employee's proposal AND confirmation for a direct (non-chat) call, as the API routes do."""
    cid = stack.confirmations.propose(employee, "direct-api", action, params)
    stack.confirmations.confirm(employee, "direct-api", cid)
    return cid


def submit_reset(stack, employee: str = EMPLOYEE_A, key: str = "k-reset") -> str:
    """Submit a password-reset request through the gateway. Returns its request ID (status PENDING)."""
    params = {"action": "password_reset", "target_employee_id": employee}
    cid = confirmed(stack, employee, "request_privileged_action", params)
    result = stack.gateway.invoke(ctx(employee), "request_privileged_action",
                                  {**params, "confirmation_id": cid, "idempotency_key": key})
    assert result.status == "PENDING_APPROVAL", result
    return result.data["request_id"]


def execute(stack, request_id: str, employee: str = EMPLOYEE_A, action: str = "password_reset",
            action_params: dict | None = None, key: str = "k-exec"):
    """Try to execute a privileged action through the gateway, with a fresh employee confirmation."""
    action_params = action_params if action_params is not None else {"target_employee_id": EMPLOYEE_A}
    cid = confirmed(stack, employee, "execute_privileged_action",
                    {"request_id": request_id, "action": action, "action_params": action_params})
    return stack.gateway.invoke(ctx(employee), "execute_privileged_action", {
        "request_id": request_id, "action": action, "action_params": action_params,
        "confirmation_id": cid, "idempotency_key": key})


def disable_enforcement(m) -> None:
    """TEST ONLY. Switch off the main runtime controls for the length of ONE test, using pytest's monkeypatch `m`
    (which undoes every change automatically). The application and the API have no switch like this.

    Disabled: the permission matrix, the approval check, the confirmation check, the ticket-ownership check and the
    gateway's employee_id check. NOT disabled: the parameter allow-list, which still refuses `decide_approval` and
    `grant_permission` (no tool exists for them anyway)."""
    import app.agent.tools as tools
    from app.agent.confirmations import ConfirmationStore
    from app.governance import permissions
    from app.governance.approvals import ApprovalService
    from app.governance.gateway import Gateway

    m.setattr(permissions, "classify", lambda role, tool: "ALLOWED")
    m.setattr(ApprovalService, "check_execution", lambda self, e, r, a, p: {"status": "APPROVED"})
    m.setattr(ConfirmationStore, "validate", lambda self, *a, **k: {})
    m.setattr(ConfirmationStore, "consume", lambda self, cid: None)  # validation is off, so there may be nothing to consume
    m.setattr(tools.rules, "employee_owns_ticket", lambda ticket, employee_id: True)
    original = Gateway.invoke

    def invoke(self, ctx, tool, params):
        return original(self, ctx, tool, {k: v for k, v in dict(params).items() if k != "employee_id"})

    m.setattr(Gateway, "invoke", invoke)
