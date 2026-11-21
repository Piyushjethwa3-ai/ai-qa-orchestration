"""
The rule-based planner: decides the NEXT action for one turn from the message, the session and what the
tools have returned so far. It returns either a ToolCall or a Reply. It never calls a tool itself, never
sees employee identity from chat text, and never decides how many steps or retries are allowed (the runner
enforces those, so a buggy or malicious planner cannot lift them).

Replies only state what a tool result supports (BR11). Retrieved document text is used as DATA to show
guidance; no instruction found in a document changes what the planner does (BR12).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.tools import DENIED, NOT_FOUND, PENDING_APPROVAL, SUCCESS, ToolResult

OUTCOMES = (
    "OUTAGE_GUIDANCE", "NEEDS_CLARIFICATION", "PENDING_CONFIRMATION", "GUIDANCE_EXISTING_TICKET",
    "TICKET_CREATED", "CANCELLED", "NOTHING_TO_CONFIRM", "TICKETS_LISTED", "TICKET_SHOWN",
    "TICKET_UNAVAILABLE", "ESCALATED", "OUTCOME_UNKNOWN", "DENIED", "PENDING_APPROVAL",
    "PRIVILEGED_STATUS", "PRIVILEGED_EXECUTED",
)


@dataclass(frozen=True)
class ToolCall:
    tool: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    outcome: str
    message: str
    sources: tuple = ()
    slots: dict = field(default_factory=dict)       # a None value deletes that slot
    proposal: dict | None = None                    # {"action":..., "params":{...}} awaiting the employee's yes
    clear_pending: bool = False
    escalation_reason: str | None = None
    ticket_id: str | None = None


@dataclass
class Turn:
    message: str                 # already redacted
    employee_id: str
    session: object
    intent: str
    observations: list = field(default_factory=list)   # [(ToolCall, ToolResult)]
    privileged: bool = False


CONFIRM_WORDS = {"yes", "y", "yes please", "confirm", "confirmed", "go ahead", "please do", "ok", "okay",
                 "sure", "retry", "try again"}
CANCEL_WORDS = {"no", "n", "cancel", "never mind", "nevermind", "stop", "forget it", "abandon"}
OS_LABEL = {"macos": "Mac", "windows": "Windows"}
_TICKET_ID = re.compile(r"(?i)\bTCK-\d+\b")
_OS_PATTERNS = (("macos", re.compile(r"(?i)\b(mac|macos|macbook|os ?x)\b")),
                ("windows", re.compile(r"(?i)\b(windows|win ?1[01]|win ?7)\b")),
                ("linux", re.compile(r"(?i)\b(linux|ubuntu)\b")))


def normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def extract_os(text: str):
    """The device named in the text, or None when none (or two conflicting devices) are named."""
    found = {name for name, pattern in _OS_PATTERNS if pattern.search(text)}
    return found.pop() if len(found) == 1 else None


def classify(text: str, session) -> str:
    t = normalise(text)
    if t in CONFIRM_WORDS:
        return "confirm"
    if t in CANCEL_WORDS:
        return "cancel"
    if _TICKET_ID.search(text):
        return "ticket_lookup"
    if "ticket" in t and any(w in t.split() for w in ("my", "show", "list", "open", "status", "check", "what")) \
            and not any(w in t for w in ("create", "raise", "log a")):
        return "my_tickets"
    if "vpn" in t:
        return "vpn"
    if session.slots.get("privileged_request_id") and any(
            w in t.split() for w in ("status", "approved", "approval", "done", "completed", "progress", "update", "been")):
        return "privileged_status"
    if ("reset" in t and "password" in t) or "locked out" in t or "forgot my password" in t:
        return "account_reset"
    if any(w in t.split() for w in ("software", "install", "licence", "license", "application", "app")):
        return "software"
    if session.slots.get("topic") and extract_os(text):
        return "continuation"
    return "unknown"


def _last(turn: Turn, tool: str):
    for call, result in reversed(turn.observations):
        if call.tool == tool:
            return result
    return None


def _doc(result: ToolResult, doc_id: str):
    return next((d for d in result.data.get("documents", []) if d["doc_id"] == doc_id), None)


def _escalate(reason: str, message: str, sources=()) -> Reply:
    return Reply("ESCALATED", message + " I'm escalating this to the IT service desk.", tuple(sources),
                 escalation_reason=reason)


class RulePlanner:
    def plan(self, turn: Turn):
        handler = {
            "confirm": self._confirm, "cancel": self._cancel, "vpn": self._vpn, "continuation": self._continuation,
            "account_reset": self._account_reset, "software": self._software, "my_tickets": self._my_tickets,
            "ticket_lookup": self._ticket_lookup, "privileged_status": self._privileged_status,
        }.get(turn.intent, self._unknown)
        return handler(turn)

    # -- confirmation ------------------------------------------------------------------------------
    def _cancel(self, turn: Turn):
        if turn.session.pending or turn.session.slots.get("topic"):
            return Reply("CANCELLED", "Okay, I've cancelled that. Nothing was created or changed.",
                         clear_pending=True, slots={"topic": None, "issue": None})
        return Reply("NOTHING_TO_CONFIRM", "There is nothing in progress to cancel.")

    def _confirm(self, turn: Turn):
        pending = turn.session.pending
        if not pending:
            return Reply("NOTHING_TO_CONFIRM", "There is nothing waiting for your confirmation. "
                         "Tell me what you need and I'll start again.")
        action = pending["action"]
        call = ToolCall(action, {**pending["params"], "confirmation_id": pending["confirmation_id"],
                                 "idempotency_key": f"{turn.session.session_id}:{pending['confirmation_id']}"})
        result = _last(turn, action)
        if result is None:
            return call
        after = getattr(self, f"_after_{action}", None)
        if after is None:
            return _escalate("unsupported_action", "I can't complete that action.")
        return after(turn, result)

    def _after_create_ticket(self, turn: Turn, result: ToolResult):
        if result.status == SUCCESS:
            ticket = result.data["ticket"]
            return Reply("TICKET_CREATED", f"Ticket {ticket['ticket_id']} has been created for you (status: "
                         f"{ticket['status']}). The ticket tool confirmed it.", ticket_id=ticket["ticket_id"],
                         clear_pending=True, slots={"last_ticket_id": ticket["ticket_id"]})
        return Reply("DENIED", "I couldn't create the ticket because your confirmation is missing or no longer "
                     "valid. Nothing was created.", clear_pending=True)

    # -- VPN -----------------------------------------------------------------------------------------
    def _continuation(self, turn: Turn):
        return self._vpn(turn) if turn.session.slots.get("topic") == "vpn" else self._unknown(turn)

    def _vpn(self, turn: Turn):
        slots = turn.session.slots
        os_ = slots.get("os")
        status = _last(turn, "get_service_status")
        if status is None:
            return ToolCall("get_service_status", {"service": "vpn"})
        if status.status != SUCCESS:
            return _escalate("status_unavailable", "I couldn't get the current VPN status, so I won't guess.")
        svc = status.data
        status_line = f"The VPN status tool reports: {svc['status']} (updated {svc['updated_at']}). {svc.get('message', '')}".strip()

        if svc["status"] == "outage":
            guide = _last(turn, "retrieve_guide")
            if guide is None:
                return ToolCall("retrieve_guide", {"query": "vpn outage", "os": os_})
            doc = _doc(guide, "KB-VPN-OUTAGE")
            return Reply("OUTAGE_GUIDANCE", f"{status_line}\nThis fits the suspected-VPN-outage process. I can't give a "
                         "recovery time because none is confirmed. Please watch the service status updates and "
                         "ask me again later.", (doc["doc_id"],) if doc else ())

        if os_ is None:
            return Reply("NEEDS_CLARIFICATION", f"{status_line}\nTo choose the right guide, which device are you "
                         "using: a Mac or a Windows PC?", slots={"topic": "vpn"})

        guide = _last(turn, "retrieve_guide")
        if guide is None:
            return ToolCall("retrieve_guide", {"query": slots.get("issue") or "vpn", "os": os_})
        device = next((d for d in guide.data["documents"] if d["os"] == os_ and d["status"] == "approved"), None)
        if device is None:
            return _escalate("no_device_specific_guidance", "I couldn't find approved VPN guidance for your device "
                             "and software version, so I won't guess.")
        tickets = _last(turn, "search_tickets")
        if tickets is None:
            return ToolCall("search_tickets", {})

        label = OS_LABEL.get(os_, os_)
        steps = device["sections"].get("Steps") or device["sections"].get("Process") or []
        guidance = (f"{status_line}\nApproved guidance for {label} ({device['doc_id']}: {device['title']}):\n"
                    + "\n".join(steps))
        sources = (device["doc_id"],)
        open_vpn = [t for t in tickets.data["tickets"]
                    if t["status"] not in ("resolved", "closed") and "vpn" in t["subject"].lower()]
        if open_vpn:
            return Reply("GUIDANCE_EXISTING_TICKET", guidance + f"\nYou already have an open VPN ticket "
                         f"({open_vpn[0]['ticket_id']}), so I have not proposed a new one.", sources,
                         ticket_id=open_vpn[0]["ticket_id"])
        proposal = {"action": "create_ticket", "params": {
            "subject": f"VPN connection problem ({label})", "description": (slots.get("issue") or "VPN problem")[:400]}}
        return Reply("PENDING_CONFIRMATION", guidance + "\nIf these steps don't fix it, I can create a support ticket "
                     "for you. Nothing has been created yet. Reply yes to confirm or no to cancel.", sources,
                     proposal=proposal)

    # -- account and software requests -----------------------------------------------------------------
    def _account_reset(self, turn: Turn):
        guide = _last(turn, "retrieve_guide")
        if guide is None:
            return ToolCall("retrieve_guide", {"query": "account password reset request",
                                               "os": turn.session.slots.get("os")})
        doc = _doc(guide, "KB-ACCOUNT-RESET")
        sources = (doc["doc_id"],) if doc else ()
        never = " I will never ask you for your password, a one-time code or a recovery code."
        if not turn.privileged:
            return _escalate("privileged_action_not_available", "I can't reset passwords. A privileged reset needs "
                             "separate IT approval and I can't request one. No reset has been requested or performed."
                             + never, sources)
        proposal = {"action": "request_privileged_action",
                    "params": {"action": "password_reset", "target_employee_id": turn.employee_id}}
        return Reply("PENDING_CONFIRMATION", "A password reset is a privileged action. I can submit a request for "
                     "separate IT approval; nothing is reset unless an IT approver approves it. Nothing has been "
                     "submitted yet. Reply yes to submit the request or no to cancel." + never, sources, proposal=proposal)

    def _software(self, turn: Turn):
        guide = _last(turn, "retrieve_guide")
        if guide is None:
            return ToolCall("retrieve_guide", {"query": "software access request", "os": turn.session.slots.get("os")})
        doc = _doc(guide, "KB-SOFTWARE-ACCESS")
        if doc is None:
            return _escalate("no_approved_guidance", "I couldn't find approved guidance for this request.")
        proposal = {"action": "create_ticket", "params": {
            "subject": "Software access request", "description": (turn.session.slots.get("issue") or turn.message)[:400]}}
        return Reply("PENDING_CONFIRMATION", f"Software access requests need the application name and the business "
                     f"reason ({doc['doc_id']}). Restricted access requires approval, and a request is not proof of "
                     "installation. I can create a support ticket for you. Nothing has been created yet. "
                     "Reply yes to confirm or no to cancel.", (doc["doc_id"],), proposal=proposal)

    # -- tickets ---------------------------------------------------------------------------------------
    def _my_tickets(self, turn: Turn):
        result = _last(turn, "search_tickets")
        if result is None:
            return ToolCall("search_tickets", {})
        tickets = result.data["tickets"]
        if not tickets:
            return Reply("TICKETS_LISTED", "You have no tickets.")
        return Reply("TICKETS_LISTED", "Your tickets:\n" + "\n".join(
            f"{t['ticket_id']} [{t['status']}] {t['subject']}" for t in tickets))

    def _ticket_lookup(self, turn: Turn):
        ticket_id = _TICKET_ID.search(turn.message).group(0).upper()
        result = _last(turn, "get_ticket")
        if result is None:
            return ToolCall("get_ticket", {"ticket_id": ticket_id})
        if result.status == SUCCESS:
            t = result.data["ticket"]
            return Reply("TICKET_SHOWN", f"{t['ticket_id']} [{t['status']}] {t['subject']}\n{t['description']}",
                         ticket_id=t["ticket_id"])
        # DENIED and NOT_FOUND get the same wording so the answer does not reveal which tickets exist.
        return Reply("TICKET_UNAVAILABLE", "I can't find a ticket with that ID that I'm able to show you.")

    def _privileged_status(self, turn: Turn):
        return self._unknown(turn)

    def _unknown(self, turn: Turn):
        return Reply("NEEDS_CLARIFICATION", "I can help with VPN problems, account access, software requests and "
                     "your own tickets. What do you need help with?")
