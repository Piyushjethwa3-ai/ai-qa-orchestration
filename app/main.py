"""
Northstar Services - IT Service Desk API (Week 1 starter).

A small, deterministic FastAPI service. There is no LLM, no database, and
no external calls here on purpose: this week is about building a service
students can read end to end and test with confidence, before AI features
are layered on top in later weeks.
"""

from fastapi import Depends, FastAPI, Header, HTTPException

from app import data, rules

app = FastAPI(
    title="Northstar Services - IT Service Desk API",
    description=(
        "Deterministic Week 1 starter API for the AI QA Orchestration "
        "training program. Employees are identified by a demo header, "
        "not by real authentication."
    ),
    version="0.1.0",
)

DEMO_HEADER_NAME = "X-Demo-Employee-ID"


def get_current_employee(
    x_demo_employee_id: str | None = Header(default=None, alias=DEMO_HEADER_NAME),
) -> dict:
    """Resolve the synthetic "current employee" for this request.

    BR01: The demo employee comes from the X-Demo-Employee-ID header, not
    from any text in the request body or URL. Raises 400 when the header
    is missing or does not match a known employee.
    """
    if not x_demo_employee_id:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required header: {DEMO_HEADER_NAME}",
        )

    employees = data.load_employees()
    employee = rules.find_employee_by_id(employees, x_demo_employee_id)

    if employee is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown demo employee id: {x_demo_employee_id}",
        )

    return employee


@app.get("/health")
def get_health() -> dict:
    """Basic health check used to confirm the API is running."""
    return {"status": "ok", "service": "northstar-it-service-desk"}


@app.get("/employees/me")
def get_my_profile(employee: dict = Depends(get_current_employee)) -> dict:
    """Return the synthetic employee selected by the X-Demo-Employee-ID header."""
    return employee


@app.get("/services/vpn/status")
def get_vpn_status() -> dict:
    """Return the current synthetic VPN service status.

    BR04: VPN service status always has a defined status value and an
    update time.
    """
    return data.load_service_status()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, employee: dict = Depends(get_current_employee)) -> dict:
    """Return one ticket, only when it belongs to the current demo employee.

    BR02: An employee cannot view another employee's ticket (403).
    BR03: A missing ticket returns 404.
    """
    tickets = data.load_tickets()
    ticket = rules.find_ticket_by_id(tickets, ticket_id)

    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket not found: {ticket_id}")

    if not rules.employee_owns_ticket(ticket, employee["employee_id"]):
        raise HTTPException(
            status_code=403,
            detail="You may not view another employee's ticket.",
        )

    return ticket
