"""
Day 2, part 2: @pytest.mark.parametrize.

Beginner note on the syntax: `@pytest.mark.parametrize("names", CASES)`
tells pytest to run the decorated test function once for every item in
CASES, feeding that item's values into the function as the arguments
named in "names" (a comma-separated string). Each `pytest.param(...)`
below is one full test case; its `id=` becomes the readable label
pytest prints for that specific run — e.g.
`test_ticket_access_scenarios[employee_a_requests_own_ticket]` —
instead of an auto-generated id like `[EMP001-TCK-1001-200]`.

This one function replaces five near-duplicate test functions and
checks, against the real API contract in app/main.py:

- an employee reading their own ticket (200)
- an employee reading the *other* employee's ticket, both directions
  (403 each way — ownership is not symmetric, so both directions are
  checked separately)
- a valid, authenticated employee requesting a well-formed ticket id
  that does not exist (404)

Overlap note (fixture demonstrations): the two 200 cases below
(`employee_a_requests_own_ticket`, `employee_b_requests_own_ticket`)
use the exact same employee/ticket pairs already demonstrated
concretely in tests/day2/test_01_fixtures.py. They are repeated here
on purpose, to show *why* parametrize is worth it (one function
instead of two near-identical ones), not to add new coverage. When
counting unique behaviors this project's Day 2 suite verifies, count
each of those two scenarios once (from test_01_fixtures.py), not
again here. The 403 and 404 cases in this file are new coverage that
test_01_fixtures.py does not exercise.
"""

import pytest

CASES = [
    pytest.param("EMP001", "TCK-1001", 200, id="employee_a_requests_own_ticket"),
    pytest.param("EMP002", "TCK-1002", 200, id="employee_b_requests_own_ticket"),
    pytest.param("EMP001", "TCK-1002", 403, id="employee_a_requests_employee_bs_ticket"),
    pytest.param("EMP002", "TCK-1001", 403, id="employee_b_requests_employee_as_ticket"),
    pytest.param(
        "EMP001", "TCK-9999", 404, id="valid_employee_requests_well_formed_missing_ticket"
    ),
]


@pytest.mark.parametrize("employee_id, ticket_id, expected_status", CASES)
def test_ticket_access_scenarios(client, auth_headers, employee_id, ticket_id, expected_status):
    # Act: every case sends the same shape of request — only the
    # employee, the requested ticket, and the expected outcome change
    # per row in CASES above.
    response = client.get(f"/tickets/{ticket_id}", headers=auth_headers(employee_id))

    # Assert: the exact status code first. No case here tolerates an
    # alternative outcome — a 200 that became a 500, or a 403 that
    # became a 404, must fail this test rather than pass loosely.
    assert response.status_code == expected_status
    body = response.json()

    if expected_status == 200:
        # Own-ticket success: the API must return the ticket that was
        # asked for, and it must be owned by the employee who asked.
        assert body["ticket_id"] == ticket_id
        assert body["employee_id"] == employee_id

    elif expected_status == 403:
        # Denied cross-employee access. The response must match the
        # exact documented error shape, and it must not leak the other
        # employee's ticket content (subject/description/status/etc.)
        # anywhere in the body — a denied request should look the same
        # whether or not the guessed ticket id was correct.
        assert body == {"detail": "You may not view another employee's ticket."}
        assert "subject" not in body
        assert "description" not in body
        assert "status" not in body

    elif expected_status == 404:
        # Missing ticket: a well-formed id (matches schemas/ticket.schema.json's
        # ^TCK-[0-9]+$ pattern) that simply is not in data/tickets.json.
        assert body == {"detail": f"Ticket not found: {ticket_id}"}
