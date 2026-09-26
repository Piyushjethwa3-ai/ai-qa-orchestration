"""
Business-rule functions for the Northstar Services IT Service Desk API.

These functions only work with plain Python data (lists and dicts) that
have already been loaded from JSON. They do not read files and do not
know anything about HTTP status codes. That keeps them simple to read,
simple to unit test, and reusable from any route.
"""


def find_employee_by_id(employees: list[dict], employee_id: str) -> dict | None:
    """Return the employee record matching employee_id, or None if not found."""
    for employee in employees:
        if employee["employee_id"] == employee_id:
            return employee
    return None


def find_ticket_by_id(tickets: list[dict], ticket_id: str) -> dict | None:
    """Return the ticket record matching ticket_id, or None if not found."""
    for ticket in tickets:
        if ticket["ticket_id"] == ticket_id:
            return ticket
    return None


def employee_owns_ticket(ticket: dict, employee_id: str) -> bool:
    """Return True only when the ticket belongs to the given employee.

    BR02: An employee cannot view another employee's ticket. This function
    is the single place that decides ownership, so the rule is easy to
    find, easy to test, and easy to (temporarily) break for training.
    """
    return ticket["employee_id"] == employee_id
