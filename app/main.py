"""
Northstar Services - IT Service Desk API (Week 1 starter).

A small, deterministic FastAPI service. There is no LLM, no database, and
no external calls here on purpose: this week is about building a service
students can read end to end and test with confidence, before AI features
are layered on top in later weeks.
"""

from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app import data, rules, runtime
from app.agent import tools as agent_tools
from app.agent.confirmations import ConfirmationError
from app.governance.approvals import ApprovalError
from app.governance.redaction import redact

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

    API-R04 (labelled BR04 in Week 1): VPN service status always has a
    defined status value and an update time.
    """
    return data.load_service_status()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, employee: dict = Depends(get_current_employee)) -> dict:
    """Return one ticket, only when it belongs to the current demo employee.

    BR02: An employee cannot view another employee's ticket (403).
    API-R03 (labelled BR03 in Week 1): A missing ticket returns 404.
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


# ---------------------------------------------------------------------------------------------------------
# Agent, tools, approvals and audit (Week 5 agent + Day 6 governance). Everything below is ADDITIVE: the
# routes above are unchanged. Identity still comes only from a header (BR01); chat text never sets it.
# ---------------------------------------------------------------------------------------------------------
APPROVER_HEADER_NAME = "X-Demo-Approver-ID"
DIRECT_SESSION_ID = "direct-api"
CONFIRMABLE_ACTIONS = ("create_ticket", "request_privileged_action", "execute_privileged_action")
TOOL_HTTP_STATUS = {
    agent_tools.SUCCESS: 200, agent_tools.PENDING_APPROVAL: 202, agent_tools.DENIED: 403,
    agent_tools.NOT_FOUND: 404, agent_tools.TIMEOUT: 504, agent_tools.FAILED: 400,
}
APPROVAL_HTTP_STATUS = {
    "unknown_request": 404, "already_decided": 409, "expired": 409, "self_approval": 403, "not_an_approver": 403,
    "invalid_decision": 400,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(_Strict):
    session_id: str
    message: str


class ToolRequest(_Strict):
    params: dict = {}


class ProposalRequest(_Strict):
    action: str
    params: dict


class DecisionRequest(_Strict):
    decision: Literal["approve", "reject"]
    reason: str = ""


def get_current_approver(
    x_demo_approver_id: str | None = Header(default=None, alias=APPROVER_HEADER_NAME),
) -> str:
    """Resolve the simulated IT approver. Only approver IDs from data/approvers.json qualify; an
    employee ID (or any chat text) never does."""
    if not x_demo_approver_id or not runtime.get_services().extras["approvals"].is_approver(x_demo_approver_id):
        raise HTTPException(status_code=403, detail=f"A valid {APPROVER_HEADER_NAME} header is required.")
    return x_demo_approver_id


@app.post("/agent/chat")
def agent_chat(body: ChatRequest, employee: dict = Depends(get_current_employee)) -> dict:
    """Send one message to the service desk agent as the header-identified employee."""
    try:
        reply = runtime.get_services().runner.handle(employee["employee_id"], body.session_id, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    result = reply.to_dict()
    result.pop("trace")  # the tool trace is QA evidence; the audit log (approver only) holds it
    return result


@app.post("/confirmations")
def propose_confirmation(body: ProposalRequest, employee: dict = Depends(get_current_employee)) -> dict:
    """Direct-API users record a proposal here, then confirm it, before a write tool will run (BR06)."""
    if body.action not in CONFIRMABLE_ACTIONS:
        raise HTTPException(status_code=400, detail="That action cannot be confirmed.")
    confirmation_id = runtime.get_services().confirmations.propose(
        employee["employee_id"], DIRECT_SESSION_ID, body.action, body.params)
    return {"confirmation_id": confirmation_id, "status": "PROPOSED"}


@app.post("/confirmations/{confirmation_id}/confirm")
def confirm_confirmation(confirmation_id: str, employee: dict = Depends(get_current_employee)) -> dict:
    """Someone else's confirmation and a missing one both answer 404, so confirmation IDs cannot be probed. The precise
    reason is recorded in the audit log, which only an IT approver can read."""
    services = runtime.get_services()
    request_id = runtime.next_request_id()

    def audit(decision: str, reason: str, result):
        services.extras["audit"].record(
            request_id=request_id, session_id=DIRECT_SESSION_ID, actor_role="employee", actor_id=employee["employee_id"],
            tool="confirm_confirmation", params={"confirmation_id": confirmation_id}, decision=decision, reason=reason,
            result_status=result, error=reason or None, confirmation_id=confirmation_id, correlation_id=None)

    try:
        services.confirmations.confirm(employee["employee_id"], DIRECT_SESSION_ID, confirmation_id)
    except ConfirmationError as exc:
        audit("DENIED", exc.internal, None)
        raise HTTPException(status_code=404 if exc.code == "unknown_confirmation" else 403, detail=exc.code)
    audit("ALLOWED", "", "CONFIRMED")
    return {"confirmation_id": confirmation_id, "status": "CONFIRMED"}


@app.post("/tools/{tool_name}")
def call_tool(tool_name: str, body: ToolRequest, response: Response,
              employee: dict = Depends(get_current_employee)) -> dict:
    """Call a tool DIRECTLY, bypassing the agent. The gateway applies exactly the same rules as for the agent."""
    services = runtime.get_services()
    ctx = agent_tools.CallContext(employee_id=employee["employee_id"], session_id=DIRECT_SESSION_ID,
                                  request_id=runtime.next_request_id(), role="employee")
    result = services.gateway.invoke(ctx, tool_name, body.params)
    response.status_code = TOOL_HTTP_STATUS[result.status]
    return {"tool": result.tool, "status": result.status, "data": redact(result.data), "error": result.error}


@app.post("/approvals/{request_id}/decision")
def decide_approval(request_id: str, body: DecisionRequest, approver_id: str = Depends(get_current_approver)) -> dict:
    """An IT approver approves or rejects a privileged request. This is the ONLY way to approve."""
    try:
        record = runtime.get_services().gateway.decide_approval(approver_id, request_id, body.decision, body.reason)
    except ApprovalError as exc:
        raise HTTPException(status_code=APPROVAL_HTTP_STATUS.get(exc.code, 400), detail=exc.code)
    return {"request_id": request_id, "status": record["status"], "decided_by": record["decided_by"]}


@app.get("/audit")
def read_audit(request_id: str | None = None, correlation_id: str | None = None,
               approver_id: str = Depends(get_current_approver)) -> dict:
    """Redacted audit records. Approvers only."""
    records = runtime.get_services().gateway.read_audit(approver_id, request_id=request_id,
                                                         correlation_id=correlation_id)
    return {"records": records, "chain_intact": runtime.get_services().extras["audit"].verify_chain()[0]}
