"""
Simulated service tools for the agent (Week 5).

Everything is local and synthetic. Tickets created here live in memory only: `data/*.json` is never
written. Each tool returns a ToolResult with one of several DISTINCT statuses (BR11), because "it
timed out", "it was denied", "it failed" and "it is pending approval" are different facts and the
agent must not blur them.

Fault injection is for tests only. `script_faults("create_ticket", ["timeout_after_success", "ok"])`
makes the next two calls to that tool misbehave in that order; with nothing scripted, tools behave
normally. The backend never injects a fault on its own.
"""

from __future__ import annotations

import copy
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app import data, rules
from app.agent.confirmations import ConfirmationError, ConfirmationStore, fingerprint
from app.governance.redaction import redact_text

SUCCESS, FAILED, TIMEOUT, DENIED, NOT_FOUND, PENDING_APPROVAL = (
    "SUCCESS", "FAILED", "TIMEOUT", "DENIED", "NOT_FOUND", "PENDING_APPROVAL")
STATUSES = (SUCCESS, FAILED, TIMEOUT, DENIED, NOT_FOUND, PENDING_APPROVAL)
FAULT_OUTCOMES = ("ok", "error", "timeout_before", "timeout_after_success")
SERVICE_STATUS_VALUES = ("operational", "degraded", "outage")


class ToolError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: str
    data: dict = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False
    internal: str | None = None  # the precise reason, for the approver-only audit log. NEVER shown to callers.

    @property
    def confirmed(self) -> bool:
        """True only when the tool itself reported success (BR11)."""
        return self.status == SUCCESS


@dataclass(frozen=True)
class CallContext:
    """Who is calling. employee_id comes from the trusted session, never from chat text (BR01)."""
    employee_id: str
    session_id: str
    request_id: str = ""
    role: str = "agent"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(params: dict, key: str, max_len: int = 500) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing or invalid parameter: {key}")
    if len(value) > max_len:
        raise ToolError(f"parameter too long: {key}")
    return value


_HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def _sections(content: str) -> dict[str, list[str]]:
    """Split a Markdown document into {heading: [non-empty lines]}; skips the title and the notice."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in content.splitlines():
        stripped = line.strip()
        match = _HEADING.match(stripped)
        if match:
            current = match.group(1)
            if line.startswith("# "):
                current = None
            else:
                sections[current] = []
            continue
        if current and stripped and not stripped.startswith(">"):
            sections[current].append(stripped)
    return sections


class ToolBackend:
    def __init__(self, *, status_fixtures: dict | None = None, corpus=None,
                 confirmations: ConfirmationStore | None = None, tickets: list | None = None, clock=_now):
        self.confirmations = confirmations if confirmations is not None else ConfirmationStore()
        self.tickets: list[dict] = copy.deepcopy(tickets if tickets is not None else data.load_tickets())
        self._status = status_fixtures if status_fixtures is not None else {"vpn": data.load_service_status()}
        self._corpus = corpus
        self._clock = clock
        self._by_key: dict[tuple, dict] = {}
        self._faults: dict[str, deque] = {}
        self.call_log: list[dict] = []
        self._handlers = {
            "get_service_status": self._get_service_status,
            "retrieve_guide": self._retrieve_guide,
            "search_tickets": self._search_tickets,
            "get_ticket": self._get_ticket,
            "create_ticket": self._create_ticket,
        }

    # -- registry / fault scripting -------------------------------------------------------------
    def register(self, name: str, handler) -> None:
        self._handlers[name] = handler

    @property
    def tool_names(self) -> tuple:
        return tuple(self._handlers)

    def script_faults(self, tool: str, outcomes: list[str]) -> None:
        for outcome in outcomes:
            if outcome not in FAULT_OUTCOMES:
                raise ValueError(f"unknown fault outcome {outcome!r}")
        self._faults[tool] = deque(outcomes)

    def calls_to(self, tool: str) -> list[dict]:
        return [c for c in self.call_log if c["tool"] == tool]

    # -- dispatch ----------------------------------------------------------------------------------
    def invoke(self, tool: str, params: dict) -> ToolResult:
        self.call_log.append({"tool": tool, "params": copy.deepcopy(params)})
        handler = self._handlers.get(tool)
        if handler is None:
            return ToolResult(tool, FAILED, error=f"unknown tool: {tool}")
        queue = self._faults.get(tool)
        fault = queue.popleft() if queue else "ok"
        if fault == "error":
            return ToolResult(tool, FAILED, error="simulated service error", retryable=True)
        if fault == "timeout_before":
            return ToolResult(tool, TIMEOUT, error="simulated timeout before the operation ran", retryable=True)
        try:
            result = handler(params)
        except ToolError as exc:
            return ToolResult(tool, FAILED, error=str(exc), retryable=exc.retryable)
        except Exception:  # never leak internals or let one tool take the agent down
            return ToolResult(tool, FAILED, error="internal tool error")
        if fault == "timeout_after_success":
            return ToolResult(tool, TIMEOUT, error="simulated timeout AFTER the operation ran", retryable=True)
        return result

    # -- tools -----------------------------------------------------------------------------------
    def _get_service_status(self, params: dict) -> ToolResult:
        service = _text(params, "service", 40).lower()
        record = self._status.get(service)
        if record is None:
            return ToolResult("get_service_status", NOT_FOUND, error=f"no status for service {service!r}")
        if record.get("status") not in SERVICE_STATUS_VALUES or not record.get("updated_at"):
            raise ToolError("service status data is invalid")
        return ToolResult("get_service_status", SUCCESS, data=dict(record))

    def _retrieve_guide(self, params: dict) -> ToolResult:
        from training_day5 import knowledge, retriever  # lazy: the agent reuses the Day 5 retriever as-is

        query = _text(params, "query", 400)
        if self._corpus is None:
            self._corpus = knowledge.load_corpus()
        result = retriever.retrieve(query=query, os=params.get("os"), top_k=3, corpus=self._corpus)
        docs = []
        for hit in result.hits:
            doc = self._corpus.get(hit.doc_id)
            docs.append({"doc_id": doc.doc_id, "title": doc.title, "os": doc.os, "status": doc.status,
                         "score": hit.score, "sections": _sections(doc.content)})
        # The retrieved TEXT is data, not instructions (BR12). It is flagged so no one mistakes it for authority.
        return ToolResult("retrieve_guide", SUCCESS, data={"documents": docs, "untrusted_text": True,
                                                            "os": result.os_normalised})

    def _search_tickets(self, params: dict) -> ToolResult:
        employee_id = _text(params, "employee_id", 20)
        own = [{"ticket_id": t["ticket_id"], "subject": t["subject"], "status": t["status"]}
               for t in self.tickets if t["employee_id"] == employee_id]
        return ToolResult("search_tickets", SUCCESS, data={"tickets": own})

    def _get_ticket(self, params: dict) -> ToolResult:
        employee_id = _text(params, "employee_id", 20)
        ticket_id = _text(params, "ticket_id", 20).upper()
        ticket = rules.find_ticket_by_id(self.tickets, ticket_id)
        if ticket is None:
            return ToolResult("get_ticket", NOT_FOUND, error="ticket not found")
        if not rules.employee_owns_ticket(ticket, employee_id):
            return ToolResult("get_ticket", DENIED, error="not your ticket")  # BR02: no ticket content in the result
        return ToolResult("get_ticket", SUCCESS, data={"ticket": dict(ticket)})

    def _create_ticket(self, params: dict) -> ToolResult:
        employee_id = _text(params, "employee_id", 20)
        subject = _text(params, "subject", 200)
        description = _text(params, "description", 500)
        key = _text(params, "idempotency_key", 100)
        content = {"subject": subject, "description": description}

        existing = self._by_key.get((employee_id, key))
        if existing is not None:  # BR08: the same request again returns the SAME ticket
            if existing["content_hash"] != fingerprint(content):
                raise ToolError("idempotency key was already used with different parameters")
            ticket = next(t for t in self.tickets if t["ticket_id"] == existing["ticket_id"])
            return ToolResult("create_ticket", SUCCESS, data={"ticket": dict(ticket), "replayed": True})

        try:  # BR06: a write needs the employee's recorded confirmation for exactly these parameters
            self.confirmations.validate(employee_id, "create_ticket", content, params.get("confirmation_id"))
        except ConfirmationError as exc:
            return ToolResult("create_ticket", DENIED, error=f"confirmation required ({exc.code})",
                              internal=f"confirmation required ({exc.internal})")

        number = max([int(t["ticket_id"].split("-")[1]) for t in self.tickets] + [1000]) + 1
        now = self._clock()
        # BR05: whatever the caller typed, a secret is never stored in a ticket (the confirmation above covered the raw text).
        ticket = {"ticket_id": f"TCK-{number}", "employee_id": employee_id, "subject": redact_text(subject),
                  "description": redact_text(description), "status": "open", "created_at": now, "updated_at": now}
        self.tickets.append(ticket)
        self._by_key[(employee_id, key)] = {"ticket_id": ticket["ticket_id"], "content_hash": fingerprint(content)}
        self.confirmations.consume(params["confirmation_id"])
        return ToolResult("create_ticket", SUCCESS, data={"ticket": dict(ticket), "replayed": False})


class DirectInvoker:
    """Week 5 invoker: calls the backend directly, always using the trusted session identity.

    Day 6 replaces this with a governed invoker that checks permissions and writes an audit record.
    """

    def __init__(self, backend: ToolBackend):
        self.backend = backend

    def invoke(self, ctx: CallContext, tool: str, params: dict) -> ToolResult:
        return self.backend.invoke(tool, {**params, "employee_id": ctx.employee_id})
