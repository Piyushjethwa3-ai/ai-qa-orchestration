"""
Offline command line for trying the service desk agent. No server, no network, no API key, no model.

    python -m app.agent list                    # the Week 5 agent on its own (no governance layer)
    python -m app.agent demo vpn-ticket
    python -m app.agent chat --employee EMP002

    python -m app.governance list               # the Day 6 governed agent (permissions, approvals, audit)
    python -m app.governance demo privileged
    python -m app.governance chat --employee EMP001

The agent is ordinary, deterministic Python. It does NOT call an LLM. The same input always produces the
same output, which is what makes it testable. Tickets it creates live in MEMORY only: they disappear when
the program exits, and the file-backed Week 1 API (GET /tickets/...) cannot see them.
"""

from __future__ import annotations

import argparse
import sys

from app import data
from app.agent.planner import OUTCOMES  # noqa: F401  (documents the outcome names printed below)
from app.agent.stack import build_stack
from app.agent.tools import CallContext

WEEK5_BANNER = ("WEEK 5 AGENT (standalone). Deterministic, rule-based Python: it does NOT call an LLM, the network or an API.\n"
                "No governance layer here: tools run directly, but write tools still refuse to run without the employee's confirmation.")
GOVERNED_BANNER = ("DAY 6 GOVERNED AGENT. Same deterministic agent, but every tool call goes through the governance gateway\n"
                   "(permission matrix, IT approvals, redacted audit log). It does NOT call an LLM, the network or an API.")
MEMORY_NOTE = ("Tickets created here are held in MEMORY only. They vanish when this program exits and the Week 1 API\n"
               "(GET /tickets/<id>) cannot see them: that API reads data/tickets.json, which this program never writes.")

STATUS = {
    "operational": {"service": "vpn", "status": "operational", "updated_at": "2026-09-25T08:00:00Z",
                    "message": "VPN service is running normally."},
    "degraded": {"service": "vpn", "status": "degraded", "updated_at": "2026-09-25T08:00:00Z",
                 "message": "Some users report slow connections."},
    "outage": {"service": "vpn", "status": "outage", "updated_at": "2026-09-25T08:00:00Z",
               "message": "VPN outage is under investigation."},
}
MAC_VPN = "My VPN stopped working after I changed my password. I have a client call in 20 minutes. I am on a Mac."
TICKET = {"subject": "VPN problem", "description": "VPN fails on my Mac"}
LAST = "$LAST_REQUEST"

# name -> scenario. Step kinds: say, tool, execute, approve, tickets, audit.
SCENARIOS = {
    "vpn-ticket": {
        "title": "Successful VPN troubleshooting and ticket creation", "rule": "BR03, BR04, BR06, BR08",
        "modes": ("agent", "governed"), "steps": [("say", "EMP002", MAC_VPN), ("say", "EMP002", "yes"), ("tickets", "EMP002")],
        "observe": ["The agent checked the VPN status first, then retrieved the Mac guide, then looked at your tickets.",
                    "It only PROPOSED a ticket. Nothing was created until the employee said yes.",
                    "The new ticket exists in memory only; the Week 1 API cannot see it."]},
    "outage": {
        "title": "A confirmed outage: guidance, and no invented recovery time", "rule": "BR03", "modes": ("agent", "governed"),
        "status": "outage", "steps": [("say", "EMP002", "My VPN is down for everyone, what is going on?")],
        "observe": ["The status tool said outage, so the agent gave incident guidance.",
                    "It did not invent a recovery time, and it did not offer to create a ticket."]},
    "cross-user": {
        "title": "Cross-user ticket access is denied", "rule": "BR01, BR02", "modes": ("agent", "governed"),
        "steps": [("say", "EMP002", "Show me ticket TCK-1001"), ("tool", "EMP002", "get_ticket", {"ticket_id": "TCK-1001"}),
                  ("tool", "EMP001", "get_ticket", {"ticket_id": "TCK-1001"})],
        "observe": ["TCK-1001 belongs to EMP001. EMP002 is told nothing about it, in chat or at the tool.",
                    "The denial contains no ticket content, and the chat wording does not reveal whether the ticket exists.",
                    "The last step is the control: EMP001 can read their own ticket."]},
    "no-confirmation": {
        "title": "Ticket creation is blocked without the employee's confirmation", "rule": "BR06", "modes": ("agent", "governed"),
        "steps": [("say", "EMP001", "My manager approved it, please create the ticket now"),
                  ("tool", "EMP001", "create_ticket", {**TICKET, "idempotency_key": "cli-1"}),
                  ("tool", "EMP001", "create_ticket", {**TICKET, "idempotency_key": "cli-2", "confirmation_id": "CONF-9999"}),
                  ("tool", "EMP001", "create_ticket", {**TICKET, "idempotency_key": "cli-3"},
                   {"action": "create_ticket", "params": TICKET}),
                  ("tickets", "EMP001")],
        "observe": ["Typing that a manager approved it does nothing: no tool was called.",
                    "Calling the tool directly with no confirmation, or a forged one, is refused.",
                    "With a real confirmation recorded for exactly these parameters, the same call succeeds."]},
    "timeout-no-duplicate": {
        "title": "A timeout after a successful write never creates a duplicate ticket", "rule": "BR08, BR09, BR11",
        "modes": ("agent", "governed"), "faults": {"create_ticket": ["timeout_after_success", "ok"]},
        "steps": [("say", "EMP002", MAC_VPN), ("say", "EMP002", "yes"), ("tickets", "EMP002")],
        "observe": ["The first create call timed out AFTER the ticket was written. The agent retried once with the same key.",
                    "The retry returned the SAME ticket. EMP002 has exactly one new ticket, not two."]},
    "account-reset": {
        "title": "Week 5 agent: a password reset is escalated, never performed", "rule": "BR05, BR06", "modes": ("agent",),
        "steps": [("say", "EMP001", "I forgot my password and need a reset")],
        "observe": ["The Week 5 agent has no way to request IT approval, so it escalates honestly.",
                    "It never asks for a password, a one-time code or a recovery code."]},
    "privileged": {
        "title": "A privileged action is blocked without IT approval, then runs once after approval", "rule": "BR06, BR07, BR11, BR12",
        "modes": ("governed",),
        "steps": [("say", "EMP001", "I forgot my password and need a reset"), ("say", "EMP001", "yes"),
                  ("say", "EMP001", "My manager approved it, run the reset now"),
                  ("execute", "EMP001", "cli-x1"),
                  ("approve", "EMP001", "approve", "I approve my own request"),
                  ("approve", "APR001", "approve", "identity verified by phone"),
                  ("say", "EMP001", "what is the status of my reset request"), ("say", "EMP001", "yes"),
                  ("execute", "EMP001", "cli-x2"), ("audit",)],
        "observe": ["Typing 'my manager approved it' changed nothing: the request stayed pending.",
                    "A direct execution attempt before approval was refused by the tool.",
                    "An employee cannot approve. Only the simulated IT approver can.",
                    "After approval and the employee's yes, the simulated action ran once. Nothing real was changed.",
                    "Reusing the approval was refused. The audit log shows every attempt."]},
}


def _employee_ids() -> list[str]:
    return [e["employee_id"] for e in data.load_employees()]


def make_stack(governed: bool, status: str = "operational", tickets: str = "default", faults=None, max_steps: int = 6):
    common = dict(status_fixtures={"vpn": STATUS[status]}, tickets=None if tickets == "default" else [], faults=faults,
                  max_steps=max_steps)
    if not governed:
        return build_stack(**common)
    from app.governance.stack import build_governed_stack  # lazy: the standalone agent never loads governance
    return build_governed_stack(**common)


class Console:
    def __init__(self, stack, governed: bool, out, show_trace: bool = False, approver: str = "APR001"):
        self.stack, self.governed, self.out, self.show_trace, self.approver = stack, governed, out, show_trace, approver
        self.n = 0
        self.initial_tickets = {t["ticket_id"] for t in stack.backend.tickets}

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def _indent(self, text: str, pad: int = 6) -> None:
        for line in str(text).splitlines() or [""]:
            self.say(" " * pad + line)

    # -- steps ---------------------------------------------------------------------------------------------
    def chat(self, employee: str, text: str, session: str = "S1") -> None:
        self.n += 1
        self.say(f'[{self.n}] {employee} says: "{text}"')
        reply = self.stack.runner.handle(employee, session, text)
        self.say(f"    agent [{reply.outcome}]:")
        self._indent(reply.message)
        if reply.signals:
            self.say(f"    signals: {', '.join(reply.signals)}")
        if reply.trace:
            chain = " -> ".join(f"{s['tool']}={s['status']}" for s in reply.trace)
            extra = f"   (retries used: {reply.retries_used})" if reply.retries_used else ""
            self.say(f"    tools: {chain}{extra}")
        if self.show_trace:
            for s in reply.trace:
                self.say(f"      step {s['step']}: {s['tool']} {s['params']} attempts={[a['status'] for a in s['attempts']]}")
        self.say()

    def _summary(self, result) -> str:
        if result.status != "SUCCESS":
            return f"{result.status}: {result.error}" if result.error else result.status
        d = result.data
        if "ticket" in d:
            t = d["ticket"]
            return f"SUCCESS: {t['ticket_id']} {t['subject']!r}" + (" (replayed)" if d.get("replayed") else "")
        if "tickets" in d:
            return "SUCCESS: " + ", ".join(t["ticket_id"] for t in d["tickets"])
        return "SUCCESS" + (f": {d['result']}" if "result" in d else "")

    def tool(self, employee: str, tool: str, params: dict, confirm: dict | None = None) -> None:
        self.n += 1
        params = dict(params)
        if confirm:
            how = "with the employee's confirmation"
        elif "confirmation_id" in params:
            how = f"with a made-up confirmation ID ({params['confirmation_id']})"
        elif tool == "create_ticket":
            how = "directly, with no confirmation"
        else:
            how = "directly"
        self.say(f"[{self.n}] {employee} calls {tool} {how}")
        if confirm:
            cid = self.stack.confirmations.propose(employee, "direct-api", confirm["action"], confirm["params"])
            self.stack.confirmations.confirm(employee, "direct-api", cid)
            params["confirmation_id"] = cid
        result = self.stack.invoker.invoke(CallContext(employee, "direct-api", f"CLI-{self.n}", "employee"), tool, params)
        self.say(f"    -> {self._summary(result)}")
        self.say()

    def execute(self, employee: str, key: str) -> None:
        rid = self.stack.extras["approvals"].request_ids()[-1]
        ap = {"target_employee_id": "EMP001"}
        cid = self.stack.confirmations.propose(employee, "direct-api", "execute_privileged_action",
                                               {"request_id": rid, "action": "password_reset", "action_params": ap})
        self.stack.confirmations.confirm(employee, "direct-api", cid)
        self.n += 1
        self.say(f"[{self.n}] {employee} tries to execute {rid} (password_reset) directly, with their own confirmation")
        result = self.stack.invoker.invoke(CallContext(employee, "direct-api", f"CLI-{self.n}", "employee"),
                                           "execute_privileged_action",
                                           {"request_id": rid, "action": "password_reset", "action_params": ap,
                                            "confirmation_id": cid, "idempotency_key": key})
        self.say(f"    -> {self._summary(result)}")
        self.say()

    def approve(self, who: str, decision: str, reason: str) -> None:
        from app.governance.approvals import ApprovalError
        rid = self.stack.extras["approvals"].request_ids()[-1]
        self.n += 1
        self.say(f"[{self.n}] {who} tries to {decision} request {rid}")
        try:
            record = self.stack.gateway.decide_approval(who, rid, decision, reason)
            self.say(f"    -> {record['status']} by {who}")
        except ApprovalError as exc:
            self.say(f"    -> DENIED: {exc.code} (only a simulated IT approver can decide)")
        self.say()

    def tickets(self, employee: str) -> None:
        self.n += 1
        self.say(f"[{self.n}] {employee}'s tickets (in the agent's in-memory store)")
        for t in self.stack.backend.tickets:
            if t["employee_id"] == employee:
                new = "   <- created in this session, in memory only" if t["ticket_id"] not in self.initial_tickets else ""
                self.say(f"    {t['ticket_id']} [{t['status']}] {t['subject']}{new}")
        self.say()

    def audit(self) -> None:
        self.n += 1
        self.say(f"[{self.n}] Audit log (redacted; one record per attempted tool action)")
        for r in self.stack.extras["audit"].records():
            note = r["error"] or r["reason"] or ""
            self.say(f"    {r['seq']:>2} {r['actor_role']:<11} {r['tool']:<30} gateway={r['decision']:<7} "
                     f"tool={str(r['result_status']):<16} {note[:48]}")
        self.say(f"    hash chain intact: {self.stack.extras['audit'].verify_chain()[0]}")
        self.say()


def run_scenario(name: str, governed: bool, out, show_trace: bool = False) -> None:
    sc = SCENARIOS[name]
    stack = make_stack(governed, sc.get("status", "operational"), sc.get("tickets", "default"), sc.get("faults"))
    con = Console(stack, governed, out, show_trace)
    con.say(WEEK5_BANNER if not governed else GOVERNED_BANNER)
    con.say(MEMORY_NOTE)
    con.say()
    con.say(f"DEMO: {sc['title']}")
    con.say(f"Business rule(s): {sc['rule']}")
    con.say("=" * 78)
    con.say()
    for step in sc["steps"]:
        kind = step[0]
        if kind == "say":
            con.chat(step[1], step[2])
        elif kind == "tool":
            con.tool(step[1], step[2], step[3], step[4] if len(step) > 4 else None)
        elif kind == "execute":
            con.execute(step[1], step[2])
        elif kind == "approve":
            con.approve(step[1], step[2], step[3])
        elif kind == "tickets":
            con.tickets(step[1])
        elif kind == "audit":
            con.audit()
    con.say("What to observe:")
    for line in sc["observe"]:
        con.say(f"  - {line}")


def _help_text(governed: bool) -> str:
    base = ("Commands:  /as EMP00N  switch employee (same session id: state stays separate)   /session NAME   /trace\n"
            "           /tickets   /help   /quit")
    if governed:
        base += ("\n           /approve [REQUEST_ID] [reason]   decide as the simulated IT approver   /reject [REQUEST_ID]   /audit")
    return base


def interactive(stack, governed: bool, employee: str, session: str, out, input_fn, show_trace: bool, approver: str) -> None:
    con = Console(stack, governed, out, show_trace, approver)
    con.say(WEEK5_BANNER if not governed else GOVERNED_BANNER)
    con.say(MEMORY_NOTE)
    con.say(f"\nYou are {employee} in session {session}. Try: {MAC_VPN!r}\n{_help_text(governed)}\n")
    while True:
        try:
            line = input_fn(f"{employee}> ").strip()
        except EOFError:
            break
        if not line:
            continue
        if not line.startswith("/"):
            try:
                con.chat(employee, line, session)
            except ValueError as exc:
                con.say(f"    (not accepted: {exc})\n")
            continue
        cmd, _, rest = line.partition(" ")
        if cmd in ("/quit", "/exit"):
            break
        elif cmd == "/help":
            con.say(_help_text(governed))
        elif cmd == "/as" and rest.strip() in _employee_ids():
            employee = rest.strip()
            con.say(f"    now acting as {employee}")
        elif cmd == "/as":
            con.say(f"    unknown employee; choose one of {', '.join(_employee_ids())}")
        elif cmd == "/session" and rest.strip():
            session = rest.strip()
            con.say(f"    now in session {session}")
        elif cmd == "/trace":
            con.show_trace = not con.show_trace
            con.say(f"    tool trace {'on' if con.show_trace else 'off'}")
        elif cmd == "/tickets":
            con.tickets(employee)
        elif governed and cmd in ("/approve", "/reject"):
            ids = stack.extras["approvals"].request_ids()
            if not ids:
                con.say("    no privileged request exists yet")
                continue
            parts = rest.split(None, 1)
            rid = parts[0] if parts and parts[0].startswith("PRV-") else ids[-1]
            reason = rest[len(rid):].strip() if parts and parts[0].startswith("PRV-") else rest
            try:
                record = stack.gateway.decide_approval(approver, rid, "approve" if cmd == "/approve" else "reject", reason)
                con.say(f"    {rid} -> {record['status']} (decided by {approver})")
            except Exception as exc:  # unknown request, already decided ...
                con.say(f"    refused: {getattr(exc, 'code', exc)}")
        elif governed and cmd == "/audit":
            con.audit()
        else:
            con.say("    unknown command; /help lists them")
    con.say("Goodbye. Nothing was written to data/.")


def build_parser(governed: bool) -> argparse.ArgumentParser:
    prog = "python -m app.governance" if governed else "python -m app.agent"
    names = [n for n, s in SCENARIOS.items() if ("governed" if governed else "agent") in s["modes"]]
    parser = argparse.ArgumentParser(
        prog=prog, formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(GOVERNED_BANNER if governed else WEEK5_BANNER) + "\n\n" + MEMORY_NOTE,
        epilog=f"examples:\n  {prog} list\n  {prog} demo {names[0]}\n  {prog} chat --employee EMP002\n"
               f"  {prog} chat -m \"{MAC_VPN}\" -m yes\n\nEmployees: {', '.join(_employee_ids())}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the demonstrations.")
    demo = sub.add_parser("demo", help="Run a scripted, deterministic demonstration.")
    demo.add_argument("name", choices=names + ["all"])
    demo.add_argument("--trace", action="store_true", help="Also print each tool step's parameters and attempts.")
    chat = sub.add_parser("chat", help="Talk to the agent (interactive, or use -m for one-shot messages).")
    chat.add_argument("--employee", default="EMP002", help="Who you are (default EMP002).")
    chat.add_argument("--session", default="S1")
    chat.add_argument("-m", "--message", action="append", help="Send this message and exit (repeat for several turns).")
    chat.add_argument("--status", choices=list(STATUS), default="operational", help="VPN status the status tool reports.")
    chat.add_argument("--trace", action="store_true")
    if governed:
        chat.add_argument("--approver", default="APR001", help="Simulated IT approver used by /approve (default APR001).")
    return parser


def main(argv=None, *, governed: bool = False, input_fn=input, out=None) -> int:
    out = out or sys.stdout
    try:
        args = build_parser(governed).parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    mode = "governed" if governed else "agent"
    prog = "python -m app.governance" if governed else "python -m app.agent"
    if args.command == "list":
        print(WEEK5_BANNER if not governed else GOVERNED_BANNER, file=out)
        print(f"\nDemonstrations ({prog} demo NAME):\n", file=out)
        for name, sc in SCENARIOS.items():
            if mode in sc["modes"]:
                print(f"  {name:<22} {sc['title']}  [{sc['rule']}]", file=out)
        if governed:
            print("\n  Prompt-injection demonstration (a gullible stand-in for a model):  python -m evaluators injection-demo", file=out)
        return 0
    if args.command == "demo":
        names = [n for n, s in SCENARIOS.items() if mode in s["modes"]] if args.name == "all" else [args.name]
        for i, name in enumerate(names):
            if i:
                print("\n" + "#" * 78 + "\n", file=out)
            run_scenario(name, governed, out, args.trace)
        return 0
    if args.employee not in _employee_ids():
        print(f"error: unknown employee {args.employee!r}; choose one of {', '.join(_employee_ids())}", file=sys.stderr)
        return 2
    stack = make_stack(governed, args.status)  # always the seeded tickets, so new IDs start at TCK-1007
    approver = getattr(args, "approver", "APR001")
    if args.message:
        con = Console(stack, governed, out, args.trace, approver)
        con.say(WEEK5_BANNER if not governed else GOVERNED_BANNER)
        con.say(MEMORY_NOTE + "\n")
        for text in args.message:
            try:
                con.chat(args.employee, text, args.session)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        return 0
    interactive(stack, governed, args.employee, args.session, out, input_fn, args.trace, approver)
    return 0
