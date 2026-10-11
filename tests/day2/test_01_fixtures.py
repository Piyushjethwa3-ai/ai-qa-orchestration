"""
Day 2, part 1: fixtures.

Two concrete tests against the real API (via TestClient, no live server
needed) — no parametrization yet, so the two fixtures underneath are
easy to see on their own before Day 2 part 2 combines them into a
parametrized test.

Fixtures used here:

- `client` (defined in tests/conftest.py): a fastapi.testclient.TestClient
  wired to the app object in app/main.py. It calls the ASGI app directly
  in-process — no network call and no `uvicorn` server needed. Every
  test file under tests/ can use it without importing anything, because
  pytest shares conftest.py fixtures with every test file below it.

- `auth_headers` (defined in tests/day2/conftest.py): a factory fixture.
  Calling `auth_headers("EMP001")` returns
  `{"X-Demo-Employee-ID": "EMP001"}` — the header
  `get_current_employee()` in app/main.py requires on every protected
  route. It exists so tests don't repeat the same header dict literal.

Files to open alongside this lesson:

- data/employees.json — the 4 synthetic employees (identities).
- data/tickets.json — the 6 synthetic tickets and which employee_id
  owns each one. This is where the expected owners below come from.
- app/main.py — `get_current_employee` (reads the header, looks up the
  employee) and `get_ticket` (the route these tests call).
- app/rules.py — `employee_owns_ticket`, the ownership check the route
  runs before returning a ticket.

The expected ticket owner in each test below is copied directly from
data/tickets.json, not read back out of the response the test is
checking — so each assertion checks the API against an independently
known fact, not against itself.
"""


def test_employee_a_retrieves_their_own_ticket(client, auth_headers):
    # Arrange: Employee A is EMP001 (Dana Whitfield). Per data/tickets.json,
    # TCK-1001 belongs to EMP001.
    employee_id = "EMP001"
    ticket_id = "TCK-1001"
    expected_owner_id = "EMP001"

    # Act: ask the API for that ticket, authenticated as employee A.
    response = client.get(f"/tickets/{ticket_id}", headers=auth_headers(employee_id))

    # Assert: request succeeded, returned the ticket that was asked for,
    # and that ticket's owner matches the known owner from the data file.
    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == ticket_id
    assert body["employee_id"] == expected_owner_id


def test_employee_b_retrieves_their_own_ticket(client, auth_headers):
    # Arrange: Employee B is EMP002 (Marcus Lee). Per data/tickets.json,
    # TCK-1002 belongs to EMP002.
    employee_id = "EMP002"
    ticket_id = "TCK-1002"
    expected_owner_id = "EMP002"

    # Act: ask the API for that ticket, authenticated as employee B.
    response = client.get(f"/tickets/{ticket_id}", headers=auth_headers(employee_id))

    # Assert: request succeeded, returned the ticket that was asked for,
    # and that ticket's owner matches the known owner from the data file.
    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == ticket_id
    assert body["employee_id"] == expected_owner_id
