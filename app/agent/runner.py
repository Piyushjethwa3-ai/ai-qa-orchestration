"""
The agent runner: runs one employee message through the planner and the tools.

The runner, not the planner, owns every control that must hold even if the planner is wrong:

- identity comes from the trusted session arguments, never from chat text (BR01)
- each tool call costs one STEP; after `max_steps` (default 6) the run stops and escalates (BR09)
- a failing or timed-out tool call is retried with the SAME parameters at most `max_retries` (default 2)
  times, then the run stops and escalates; the same idempotency key makes a retried write safe (BR08, BR09)
- an unconfirmed write is reported as unknown, never as success (BR11)
- stored text, traces and replies are redacted (BR05)
- state is per (employee, session) (BR10)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import count

from app.agent.confirmations import ConfirmationError, ConfirmationStore
from app.agent.planner import Reply, RulePlanner, ToolCall, Turn, classify, extract_os
from app.agent.sessions import SessionStore
from app.agent.tools import FAILED, TIMEOUT, CallContext
from app.governance.redaction import redact, redact_text

WRITE_TOOLS = ("create_ticket", "request_privileged_action", "execute_privileged_action")
MAX_MESSAGE_CHARS = 2000


@dataclass
class AgentReply:
    request_id: str
    session_id: str
    employee_id: str
    outcome: str
    message: str
    sources: list = field(default_factory=list)
    ticket_id: str | None = None
    escalation_reason: str | None = None
    steps_used: int = 0
    retries_used: int = 0
    stop_reason: str | None = None
    signals: list = field(default_factory=list)
    pending_confirmation_id: str | None = None
    trace: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class AgentRunner:
    def __init__(self, invoker, sessions: SessionStore, confirmations: ConfirmationStore, planner=None, *,
                 max_steps: int = 6, max_retries: int = 2, privileged: bool = False):
        self.invoker = invoker
        self.sessions = sessions
        self.confirmations = confirmations
        self.planner = planner if planner is not None else RulePlanner()
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.privileged = privileged
        self._request_ids = count(1)

    # -- one tool call, with the retry limit -------------------------------------------------------
    def _call(self, ctx: CallContext, call: ToolCall):
        attempts = []
        for number in range(1, self.max_retries + 2):
            result = self.invoker.invoke(ctx, call.tool, dict(call.params))  # identical params every attempt
            attempts.append({"attempt": number, "status": result.status, "error": result.error})
            if result.status == TIMEOUT or (result.status == FAILED and result.retryable):
                continue
            break
        return result, attempts

    def _gave_up(self, call: ToolCall, result, attempts: list) -> tuple[Reply, str]:
        if call.tool in WRITE_TOOLS:
            if result.status == TIMEOUT:
                return (Reply("OUTCOME_UNKNOWN",
                              "The request timed out and I could not confirm whether it completed, so I can't tell you "
                              "it succeeded or that it failed. I'm escalating this to the IT service desk. Reply 'retry' "
                              "and I'll check again without creating a duplicate.",
                              escalation_reason=f"tool_retries_exhausted:{call.tool}"),
                        f"tool_retries_exhausted:{call.tool}")
            reason = f"tool_retries_exhausted:{call.tool}" if result.retryable else f"tool_failed:{call.tool}"
            return (Reply("ESCALATED", "The tool did not confirm that the request completed, so I am not reporting it "
                          "as done. I'm escalating this to the IT service desk. Reply 'retry' to try again.",
                          escalation_reason=reason), reason)
        reason = f"tool_retries_exhausted:{call.tool}" if result.retryable else f"tool_failed:{call.tool}"
        what = "timed out" if result.status == TIMEOUT else "failed"
        return (Reply("ESCALATED", f"The {call.tool} tool {what} after {len(attempts)} attempt(s), so I'm stopping "
                      "instead of guessing. I'm escalating this to the IT service desk.", escalation_reason=reason), reason)

    # -- one employee message ------------------------------------------------------------------------
    def handle(self, employee_id: str, session_id: str, message: str) -> AgentReply:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty text")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message is longer than {MAX_MESSAGE_CHARS} characters")
        session = self.sessions.get(employee_id, session_id)
        request_id = f"REQ-{next(self._request_ids):04d}"
        ctx = CallContext(employee_id=employee_id, session_id=session_id, request_id=request_id)

        clean = redact_text(message.strip())
        signals = []
        if clean != message.strip():
            signals.append("sensitive_input_redacted")
        if {m.upper() for m in re.findall(r"(?i)\bEMP\d+\b", clean)} - {employee_id}:
            signals.append("identity_claim_ignored")  # BR01: the session identity is unchanged
        SessionStore.remember(session, "user", clean)

        intent = classify(clean, session)
        pending = session.pending
        if intent == "confirm" and pending:
            try:  # only the employee's own turn can confirm; the tool re-checks this server-side
                self.confirmations.confirm(employee_id, session_id, pending["confirmation_id"])
            except ConfirmationError:
                pass
        elif pending and intent != "cancel":
            self.confirmations.cancel(pending["confirmation_id"])
            session.pending = None
            signals.append("pending_request_abandoned")
        detected = extract_os(clean)
        if detected:
            session.slots["os"] = detected
        if intent in ("vpn", "software"):
            session.slots.update(topic="vpn" if intent == "vpn" else "software", issue=clean[:400])

        turn = Turn(message=clean, employee_id=employee_id, session=session, intent=intent, privileged=self.privileged)
        steps = retries = 0
        trace: list = []
        stop_reason = None
        while True:
            action = self.planner.plan(turn)
            if isinstance(action, Reply):
                reply = action
                break
            if steps >= self.max_steps:
                stop_reason = "step_limit_exhausted"
                reply = Reply("ESCALATED", f"I've used the limit of {self.max_steps} steps for one request without "
                              "finishing, so I'm stopping. I'm escalating this to the IT service desk.",
                              escalation_reason="step_limit_exhausted")
                break
            steps += 1
            result, attempts = self._call(ctx, action)
            retries += len(attempts) - 1
            trace.append({"step": steps, "tool": action.tool, "params": redact(action.params), "attempts": attempts,
                          "status": result.status, "confirmed": result.confirmed})
            if result.status in (FAILED, TIMEOUT):
                reply, stop_reason = self._gave_up(action, result, attempts)
                break
            turn.observations.append((action, result))

        pending_id = None
        if reply.proposal:
            pending_id = self.confirmations.propose(employee_id, session_id, reply.proposal["action"],
                                                    reply.proposal["params"])
            session.pending = {"confirmation_id": pending_id, **reply.proposal}
        elif reply.clear_pending:
            if session.pending:
                self.confirmations.cancel(session.pending["confirmation_id"])
            session.pending = None
        for key, value in reply.slots.items():
            if value is None:
                session.slots.pop(key, None)
            else:
                session.slots[key] = value
        if session.pending and not pending_id:
            pending_id = session.pending["confirmation_id"]

        text = redact_text(reply.message)
        SessionStore.remember(session, "agent", text)
        return AgentReply(request_id=request_id, session_id=session_id, employee_id=employee_id, outcome=reply.outcome,
                          message=text, sources=list(reply.sources), ticket_id=reply.ticket_id,
                          escalation_reason=reply.escalation_reason, steps_used=steps, retries_used=retries,
                          stop_reason=stop_reason, signals=signals, pending_confirmation_id=pending_id, trace=trace)
