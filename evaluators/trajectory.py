"""
Trajectory evaluator (Week 5).

A "trajectory" is the sequence of tool calls and state changes behind an answer. This evaluator runs each
case on a FRESH agent stack, then checks, from the evidence rather than the wording:

- the outcome of every turn
- the logical tool sequence and selected parameters
- how many times each tool was actually called (retries included)
- the stored state: how many tickets exist now that did not exist before
- required evidence (document IDs), required signals, escalation and stop reasons
- prohibited tools and prohibited text, searched in replies, traces, session history, stored tickets and (when
  governed) the audit log

A case runs in one of three modes (`setup.mode`): "plain" (default, the Week 5 agent), "governed" (every tool
call through the Day 6 gateway) or "governed_privileged" (governed, with the password-reset flow switched on).
Besides chat messages, a turn can be a pseudo step: an IT approver decision, an actual attempt to execute the
privileged action, a clock advance (approval expiry), or the set-up for the prompt-injection case.

It never edits an expectation to make a case pass. A mismatch is reported as FAIL with the reason.
Nothing here uses a language model: it evaluates the deterministic, rule-based agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.agent.stack import build_stack
from app.agent.tools import CallContext
from app.governance.approvals import ApprovalError
from app.governance.redaction import redact

DATASET_PATH = Path(__file__).resolve().parent.parent / "datasets" / "agent" / "trajectory_cases.json"
EVALUATOR_VERSION = "trajectory-v1"
REQUIRED_FIELDS = ("case_id", "requirement_ids", "category", "risk", "employee_context", "input", "fixture_version",
                   "expected_evidence", "expected_behaviour", "prohibited_behaviour", "evaluator_type")
STATUS_FIXTURES = {
    "operational": {"vpn": {"service": "vpn", "status": "operational", "updated_at": "2026-11-20T08:00:00Z",
                            "message": "VPN service is running normally."}},
    "degraded": {"vpn": {"service": "vpn", "status": "degraded", "updated_at": "2026-11-20T08:00:00Z",
                         "message": "Some users report slow connections."}},
    "outage": {"vpn": {"service": "vpn", "status": "outage", "updated_at": "2026-11-20T08:00:00Z",
                       "message": "VPN outage is under investigation."}},
}


def load_dataset(path: Path = DATASET_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dataset_sha256(path: Path = DATASET_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_dataset(dataset: dict) -> list[str]:
    problems, seen = [], set()
    for case in dataset.get("cases", []):
        cid = case.get("case_id", "?")
        for name in REQUIRED_FIELDS:
            if name not in case:
                problems.append(f"{cid}: missing field {name}")
        if cid in seen:
            problems.append(f"{cid}: duplicate case_id")
        seen.add(cid)
        eb = case.get("expected_behaviour", {})
        if len(eb.get("outcomes", [])) != len(case.get("input", [])):
            problems.append(f"{cid}: outcomes must have one entry per input turn")
        for rx in case.get("prohibited_behaviour", {}).get("phrases_regex", []):
            try:
                re.compile(rx)
            except re.error as exc:
                problems.append(f"{cid}: bad regex {rx!r}: {exc}")
    return problems


class _Clock:
    """A clock a case can move forward, so approval expiry never needs a real wait."""
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def default_stack_factory(setup: dict):
    mode = setup.get("mode", "plain")
    common = dict(status_fixtures=STATUS_FIXTURES[setup.get("status", "operational")],
                  tickets=None if setup.get("tickets") == "default" else [], faults=setup.get("faults"),
                  max_steps=setup.get("max_steps", 6), max_retries=setup.get("max_retries", 2))
    if mode == "plain":
        return build_stack(**common)
    from app.governance.stack import build_governed_stack  # lazy: a plain run never loads governance

    clock = _Clock()
    stack = build_governed_stack(**common, privileged_flow=(mode == "governed_privileged"), clock=clock,
                                 audit_clock=lambda: "2026-11-21T00:00:00Z")
    stack.extras["clock"] = clock
    if setup.get("poisoned_retrieval"):
        from evaluators import injection_demo
        injection_demo.poison_retrieval(stack.backend)
        stack.runner.planner = injection_demo.GullibleInjectedPlanner(stack.extras)
    return stack


def _subset(expected: dict, actual: dict) -> bool:
    return all(actual.get(k) == v for k, v in expected.items())


def _pseudo(outcome: str, trace=None, message: str = "") -> dict:
    trace = trace or []
    return {"request_id": "", "outcome": outcome, "message": message, "sources": [], "ticket_id": None,
            "escalation_reason": None, "steps_used": len(trace), "retries_used": 0, "stop_reason": None,
            "signals": [], "trace": trace, "pending_confirmation_id": None}


def _confirm_execute(stack, employee: str, request_id: str, action: str, action_params: dict) -> tuple[str, dict]:
    params = {"request_id": request_id, "action": action, "action_params": action_params}
    cid = stack.confirmations.propose(employee, "direct-api", "execute_privileged_action", params)
    stack.confirmations.confirm(employee, "direct-api", cid)
    return cid, params


def _apply_pseudo_step(stack, spec: dict, default_employee: str, number: int) -> dict:
    approvals = stack.extras["approvals"]
    if "approver" in spec:
        want = spec["approver"]
        try:
            record = stack.gateway.decide_approval(want["id"], approvals.request_ids()[-1], want["decision"],
                                                   want.get("reason", ""))
            return _pseudo(record["status"])
        except ApprovalError as exc:
            return _pseudo(f"DENIED:{exc.code}")
    if "advance_clock" in spec:
        stack.extras["clock"].advance(spec["advance_clock"])
        return _pseudo("CLOCK_ADVANCED")
    if spec.get("prepare_execute_confirmation"):
        rid = approvals.request_ids()[-1]
        cid, _ = _confirm_execute(stack, default_employee, rid, "password_reset", {"target_employee_id": default_employee})
        stack.extras["execute_confirmation_id"] = cid
        return _pseudo("CONFIRMATION_READY")
    if "execute" in spec:  # an ACTUAL attempt to run the privileged action, through the real gateway and tool
        want = spec["execute"]
        employee = want.get("employee_id", default_employee)
        action = want.get("action", "password_reset")
        action_params = want.get("action_params", {"target_employee_id": default_employee})
        rid = approvals.request_ids()[-1]
        cid, params = _confirm_execute(stack, employee, rid, action, action_params)
        call = {**params, "confirmation_id": cid, "idempotency_key": want.get("key", f"traj-exec-{number}")}
        result = stack.gateway.invoke(CallContext(employee, "direct-api", f"TRAJ-{number}", "employee"),
                                      "execute_privileged_action", call)
        step = {"step": 1, "tool": "execute_privileged_action", "params": redact(call), "status": result.status,
                "attempts": [{"attempt": 1, "status": result.status, "error": result.error}],
                "confirmed": result.confirmed}
        return _pseudo(result.status, [step])
    raise ValueError(f"unknown turn: {sorted(spec)}")


def evaluate_case(case: dict, stack_factory=default_stack_factory) -> dict:
    stack = stack_factory(case.get("setup", {}))
    context = case["employee_context"]
    before = {t["ticket_id"] for t in stack.backend.tickets}
    replies = []
    for number, turn in enumerate(case["input"], start=1):
        spec = turn if isinstance(turn, dict) else {"message": turn}
        if "message" in spec:
            replies.append(stack.runner.handle(spec.get("employee_id", context["employee_id"]),
                                               spec.get("session_id", context["session_id"]), spec["message"]).to_dict())
        else:
            replies.append(_apply_pseudo_step(stack, spec, context["employee_id"], number))

    exp, bad, findings = case["expected_behaviour"], case["prohibited_behaviour"], []
    traces = [step for r in replies for step in r["trace"]]
    tool_sequence = [step["tool"] for step in traces]
    new_tickets = [t for t in stack.backend.tickets if t["ticket_id"] not in before]
    extras = stack.extras or {}

    outcomes = [r["outcome"] for r in replies]
    if outcomes != exp["outcomes"]:
        findings.append(f"outcomes {outcomes} != expected {exp['outcomes']}")
    if tool_sequence != exp["tool_sequence"]:
        findings.append(f"tool sequence {tool_sequence} != expected {exp['tool_sequence']}")
    if len(new_tickets) != exp["tickets_created"]:
        findings.append(f"stored state: {len(new_tickets)} new ticket(s), expected {exp['tickets_created']}")
    for tool, n in exp.get("backend_calls", {}).items():
        actual = len(stack.backend.calls_to(tool))
        if actual != n:
            findings.append(f"{tool} was called {actual} time(s) (retries included), expected {n}")
    for want in exp.get("tool_params", []):
        if not any(s["tool"] == want["tool"] and _subset(want["params"], s["params"]) for s in traces):
            findings.append(f"no {want['tool']} call with parameters {want['params']}")
    for doc_id in case["expected_evidence"]:
        if not any(doc_id in r["sources"] for r in replies):
            findings.append(f"expected evidence {doc_id} was not cited")
    for signal in exp.get("signals", []):
        if not any(signal in r["signals"] for r in replies):
            findings.append(f"expected signal {signal} was not raised")
    if "escalation_reason" in exp and not any(r["escalation_reason"] == exp["escalation_reason"] for r in replies):
        findings.append(f"expected escalation reason {exp['escalation_reason']}")
    if "stop_reason" in exp and not any(r["stop_reason"] == exp["stop_reason"] for r in replies):
        findings.append(f"expected stop reason {exp['stop_reason']}")
    if "max_steps_used" in exp and any(r["steps_used"] > exp["max_steps_used"] for r in replies):
        findings.append(f"a turn used more than {exp['max_steps_used']} steps")
    for text in exp.get("reply_contains", []):
        if text.lower() not in replies[-1]["message"].lower():
            findings.append(f"final reply does not contain {text!r}")

    # Governance expectations: what the boundary actually did, read from the steps and the stored state.
    if "trace_statuses" in exp:
        statuses = [s["status"] for s in traces]
        if statuses != exp["trace_statuses"]:
            findings.append(f"tool statuses {statuses} != expected {exp['trace_statuses']}")
    if "denial_errors" in exp:
        errors = [(s["attempts"][-1]["error"] or "") for s in traces if s["status"] == "DENIED"]
        if len(errors) != len(exp["denial_errors"]) or not all(
                want.lower() in got.lower() for want, got in zip(exp["denial_errors"], errors)):
            findings.append(f"denial reasons {errors} do not match expected {exp['denial_errors']}")
    if "privileged_executions" in exp and len(extras.get("executions", {})) != exp["privileged_executions"]:
        findings.append(f"{len(extras.get('executions', {}))} privileged execution(s), expected {exp['privileged_executions']}")
    for rid, want_status in exp.get("approval_status", {}).items():
        record = extras["approvals"].get(rid)
        if (record or {}).get("status") != want_status:
            findings.append(f"approval {rid} is {(record or {}).get('status')}, expected {want_status}")
    audit_text = ""
    if "audit" in extras:
        audit_records = extras["audit"].records()
        audit_text = json.dumps(audit_records)
        if not extras["audit"].verify_chain()[0]:
            findings.append("audit hash chain is broken")
        missing = sorted(set(exp.get("audit_tools_include", [])) - {r["tool"] for r in audit_records})
        if missing:
            findings.append(f"no audit record for {missing}")

    for tool in bad.get("tools", []):
        if tool in tool_sequence:
            findings.append(f"prohibited tool {tool} was called")
    searchable = json.dumps(replies) + json.dumps(new_tickets) + audit_text + json.dumps(
        [s.history for s in stack.sessions._sessions.values()])
    for rx in bad.get("phrases_regex", []):
        if re.search(rx, searchable):
            findings.append(f"prohibited text matched /{rx}/")

    return {"case_id": case["case_id"], "requirement_ids": case["requirement_ids"], "category": case["category"],
            "risk": case["risk"], "result": "FAIL" if findings else "PASS", "findings": findings,
            "outcomes": outcomes, "tool_sequence": tool_sequence, "tickets_created": len(new_tickets),
            "why": case.get("why", "")}


def run_dataset(dataset: dict | None = None, case_ids=None, stack_factory=default_stack_factory) -> list[dict]:
    dataset = dataset or load_dataset()
    cases = [c for c in dataset["cases"] if not case_ids or c["case_id"] in case_ids]
    return [evaluate_case(c, stack_factory) for c in cases]


def summarise(results: list[dict]) -> dict:
    failed = [r["case_id"] for r in results if r["result"] == "FAIL"]
    critical_failed = [r["case_id"] for r in results if r["result"] == "FAIL" and r["risk"] == "critical"]
    return {"total": len(results), "passed": len(results) - len(failed), "failed": len(failed),
            "failed_case_ids": failed, "critical_failed_case_ids": critical_failed}
