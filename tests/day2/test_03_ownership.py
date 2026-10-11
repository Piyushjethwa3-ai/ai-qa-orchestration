"""
Day 2, part 3: ownership (BR02), both directions -- plus proof these
tests actually catch it if BR02 breaks.

Enforcement location (read this first): the ownership check lives in
exactly one function, `employee_owns_ticket` in app/rules.py, and it is
called exactly once, inside `get_ticket` in app/main.py, after the
ticket is found and before it is returned:

    if not rules.employee_owns_ticket(ticket, employee["employee_id"]):
        raise HTTPException(status_code=403, detail="...")

Two real API tests, one per direction:

- test_employee_a_cannot_view_employee_bs_ticket: EMP001 (Employee A,
  owns TCK-1001) requests TCK-1002, which belongs to EMP002.
- test_employee_b_cannot_view_employee_as_ticket: EMP002 (Employee B,
  owns TCK-1002) requests TCK-1001, which belongs to EMP001.

Both directions are checked separately on purpose. The code above only
ever compares "the ticket in front of it" to "the caller's own id" --
it has no wider concept of a two-way relationship -- so a bug could
plausibly break one direction without breaking the other.

Each test also checks that the 403 body contains nothing about the
real ticket (no subject/description/status): a denied request must
look identical whether or not the caller's guess was otherwise close.

## Fault injection: --day2-fault=ownership

Run:

    python -m pytest tests/day2/test_03_ownership.py --day2-fault=ownership -v

This makes the `_maybe_break_ownership_enforcement` fixture below
monkeypatch `app.rules.employee_owns_ticket` to always return True --
simulating that BR02 check being deleted or broken -- but only for
tests in this file, and only for the few milliseconds each individual
test runs.

In beginner terms, what breaks: with the patch active,
`get_ticket` still runs the `if not rules.employee_owns_ticket(...)`
line, but that call now always reports "yes, this is your ticket" --
so the 403 branch never executes. The endpoint answers every ticket
request with a 200 and the ticket's real contents, regardless of who
is asking. Both tests below still assert `response.status_code == 403`
(the assertions are never changed for the fault run), so under the
fault they fail loudly with something like
`assert 200 == 403` -- concrete, readable proof that these two tests
would catch a real regression in `employee_owns_ticket`.

Why this counts as "isolated": pytest's built-in `monkeypatch` fixture
is function-scoped, so it automatically restores the original
`employee_owns_ticket` the instant each test function returns -- pass,
fail, or error -- with no cleanup code written here. The patch:

- never touches app/rules.py on disk,
- never runs unless --day2-fault=ownership is explicitly passed,
- never changes data/tickets.json or data/employees.json,
- never disables the identity/header check (BR01) -- only the
  ownership comparison,
- and cannot reach a real running instance of the API (e.g. one
  started with `uvicorn app.main:app`), because that process never
  imports pytest or this file.

Do not mark the fault-mode outcome xfail. When the fault is active,
these two tests are supposed to genuinely FAIL, in bright red --
that failure is the entire point, the evidence that the tests detect a
broken ownership check. xfail-ing them would hide exactly the signal
this drill exists to produce.
"""

import pytest

from app import rules


@pytest.fixture(autouse=True)
def _maybe_break_ownership_enforcement(request, monkeypatch):
    """Apply --day2-fault=ownership, scoped to this file only.

    No-op (BR02 stays fully enforced) unless the flag was passed on the
    command line. When it was, this swaps in a fake
    `employee_owns_ticket` that always returns True for the one test
    currently running; `monkeypatch` reverts the swap automatically as
    soon as that test function returns.
    """
    if request.config.getoption("--day2-fault") == "ownership":
        monkeypatch.setattr(rules, "employee_owns_ticket", lambda ticket, employee_id: True)


def test_employee_a_cannot_view_employee_bs_ticket(client, auth_headers):
    # Arrange: EMP001 is Employee A. TCK-1002 belongs to EMP002
    # (Employee B), per data/tickets.json.
    employee_id = "EMP001"
    ticket_id = "TCK-1002"

    # Act: exercise the real endpoint.
    response = client.get(f"/tickets/{ticket_id}", headers=auth_headers(employee_id))

    # Assert: denied, with the exact documented error body -- and
    # nothing about the real ticket (subject/description/status)
    # leaked alongside it.
    assert response.status_code == 403
    body = response.json()
    assert body == {"detail": "You may not view another employee's ticket."}
    assert "subject" not in body
    assert "description" not in body
    assert "status" not in body


def test_employee_b_cannot_view_employee_as_ticket(client, auth_headers):
    # Arrange: EMP002 is Employee B. TCK-1001 belongs to EMP001
    # (Employee A), per data/tickets.json.
    employee_id = "EMP002"
    ticket_id = "TCK-1001"

    # Act: exercise the real endpoint.
    response = client.get(f"/tickets/{ticket_id}", headers=auth_headers(employee_id))

    # Assert: same contract, opposite direction.
    assert response.status_code == 403
    body = response.json()
    assert body == {"detail": "You may not view another employee's ticket."}
    assert "subject" not in body
    assert "description" not in body
    assert "status" not in body
