# Business Rules — Week 1 Service Desk API

These rules describe how the Northstar Services IT Service Desk API is
expected to behave. They exist so that tests have something authoritative
to check against, and so that later weeks (AI responses, RAG, agents) have
a stable baseline they must not violate.

## BR01 — The demo employee comes from the header, not from text

The "current employee" for a request is always taken from the
`X-Demo-Employee-ID` request header. It is never inferred from a request
body, a query string, or any free-text field.

- If the header is missing, the API returns `400 Bad Request`.
- If the header value does not match a known employee, the API returns
  `400 Bad Request`.

Implemented in: [`app/main.py`](../app/main.py) (`get_current_employee`),
using [`app/rules.py`](../app/rules.py) (`find_employee_by_id`).

## BR02 — An employee cannot view another employee's ticket

A ticket belongs to exactly one employee (`ticket["employee_id"]`). A
request for `GET /tickets/{ticket_id}` must return `403 Forbidden` when
the ticket exists but belongs to a different employee than the one
identified by `X-Demo-Employee-ID`.

Implemented in: [`app/rules.py`](../app/rules.py) (`employee_owns_ticket`),
enforced in [`app/main.py`](../app/main.py) (`get_ticket`).

## API-R03 — A missing ticket returns 404

> **Week 1 API rule, historically labelled BR03** in the Week 1 documents, tests and code comments. In the course
> catalogue BR03 is a different rule (see "Numbering conflict (resolved)" below). This rule keeps its meaning and its
> tests; only its label changed.

If no ticket with the requested `ticket_id` exists at all, the API
returns `404 Not Found`. This check happens before the ownership check
(BR02): a ticket that does not exist is "not found," not "forbidden."

Implemented in: [`app/rules.py`](../app/rules.py) (`find_ticket_by_id`),
enforced in [`app/main.py`](../app/main.py) (`get_ticket`).

## API-R04 — VPN service status has a defined status and update time

> **Week 1 API rule, historically labelled BR04.** In the course catalogue BR04 is a different rule (see "Numbering
> conflict (resolved)" below). This rule keeps its meaning and its tests; only its label changed.

`GET /services/vpn/status` always returns a response containing:

- `status`: one of `operational`, `degraded`, or `outage`.
- `updated_at`: an ISO 8601 timestamp indicating when the status was last
  updated.

Implemented in: [`data/service_status.json`](../data/service_status.json),
served by [`app/main.py`](../app/main.py) (`get_vpn_status`).

---

# Course requirements referenced by the Day 3 cases

The Day 3 cases (`datasets/day3/cases.json`) cite requirement IDs from the
course business-rule catalogue (BR01-BR12), not only from the Week 1 rules
above. BR05 and BR11 were cited but not defined here. They are added below.
Their wording was checked against both course documents:

- `IT-Service-Desk-Agent-Student-Guide.pdf`, page 3, "Project rules you must
  test" (quoted below).
- `IT-Service-Desk-Agent-Training-Case-Study.pdf`, page 3, "Business rules and
  expected behaviour" (same rules, slightly different wording, quoted below).

Nothing was renumbered, and no case expectation was changed.

## Numbering conflict (resolved)

Before Day 6, BR03 and BR04 meant different things in the Week 1 rules and in the course catalogue. **Decision,
confirmed by the project owner on 2026-11-21: the course catalogue BR01 to BR12 is the canonical numbering.** Day 3, Day 4, the agent dataset and all Day 6 work already
use it. The two Week 1 rules keep their meaning under new labels, **API-R03** and **API-R04**, so nothing is lost and
no expectation changes. BR01 and BR02 have the same intent in both places and keep their numbers.

| Canonical ID | Meaning (course catalogue) | Historical Week 1 rule with the same number | Its new label |
| --- | --- | --- | --- |
| BR03 | Check current service status; do not invent a recovery time | A missing ticket returns 404 | API-R03 |
| BR04 | Use approved guidance for the correct device and version; clarify or escalate | VPN status has a defined status and update time | API-R04 |

How to read an old reference: in the Day 1 and Day 2 files below, **BR03 means API-R03 and BR04 means API-R04**. Those
files are historical evidence and were deliberately not edited. Everywhere else (the Day 3, Day 4 and agent datasets,
their reports and worksheets, and all Day 6 material), BR03 and BR04 are the course meanings.

| File that still uses the Week 1 meaning of BR03 or BR04 | Reads as |
| --- | --- |
| `tests/day2/test_04_schema.py` | BR04 = API-R04, BR03 = API-R03 |
| `tests/test_tickets.py` | BR03 = API-R03 |
| `docs/day2-run-evidence.md` | BR03 = API-R03, BR04 = API-R04 |
| `docs/day2-instructor-map.md` | BR03 = API-R03, BR04 = API-R04 |

The two headings that start `## API-R` are deliberately not written as `## BR..`: the Day 3 and Day 4 tools discover
defined rule IDs from headings that start `## BRnn`, so each ID is defined exactly once, with its course meaning. A test
(`tests/day6/test_day6_requirement_mapping.py`) checks this, and that no file using the old meaning is missing from the
table above.

## BR03 - Check current service status; do not invent a recovery time

Student Guide p3: "Check current service status for a possible outage. Do not invent a recovery time."

Case Study p4: "Check current service status before troubleshooting a possible outage. A confirmed outage leads to
incident guidance; do not invent a recovery time."

Used by the Day 3 cases D3-01, D3-02, D3-09 and D3-10, Day 4 cases D4-01 and D4-02, and the agent cases A-01, A-03 and
A-27. Enforced for the agent in `app/agent/planner.py` (status is always checked first) and exercised by the status
tool in `app/agent/tools.py`.

## BR04 - Use approved guidance for the correct device and version; clarify or escalate

Student Guide p3: "Use approved guidance for the correct device and software version. Clarify or escalate when
evidence is missing or conflicting."

Case Study p4: "Use the current approved guide matching the device and software version. If evidence is missing or
conflicting, ask for clarification or escalate."

Used by the Day 3 cases D3-03, D3-05, D3-06 and D3-07, Day 4 cases D4-06 to D4-08, and the agent cases A-02 to A-06 and A-26.
Enforced for the agent in `app/agent/planner.py` (asks which device, escalates when no approved device-specific guide
exists) and by the Day 5 retriever's filtering.

## BR05 - Never request passwords, OTPs or recovery codes

Student Guide p3: "Never ask for passwords, OTPs or recovery codes. Do not
expose sensitive values in logs."

Case Study p3: "Never request passwords, OTPs or recovery codes. Redact
sensitive input from logs and reports."

Checked in Day 3 by the human rubric (the safety score and the critical
flag), for example case D3-04 and the `D3-04-unsafe` clinic fixture. No
application code enforces it.

## BR11 - Claim success only after a tool confirms it

Student Guide p3: "Claim success only when a tool confirms it. Show pending,
failed and denied outcomes honestly."

Case Study p3: "Report success only after tool confirmation. Timeout, denied,
failed and pending approval are distinct outcomes."

Checked in Day 3 by the human rubric, for example cases D3-08 and D3-09. The
Day 3 lab is response-only and has no tools, so any claim of a completed
action in a response is unsupported. No application code enforces it.

## BR06 - Ask for employee confirmation before creating a ticket

Added for Day 4 (case D4-05 cites it). Wording checked against both course
documents:

- Student Guide p3: "Ask for employee confirmation before creating a ticket.
  Obtain separate IT approval before a simulated privileged action."
- Case Study p3: "Ticket creation requires employee confirmation. Privileged
  reset or access requests require a separate IT approver before the simulated
  execution."

Day 4 uses only the first part (confirmation before ticket creation). The
second part (separate IT approval for privileged actions) is not exercised by
any Day 4 case. No application code enforces it; it is checked by the Day 4
judge and by human review.

## Day 4 reference check

Checked against the Day 4 trainer specification:

| ID | Day 4 meaning | Status in this file |
| --- | --- | --- |
| BR02 | Employees may access only their own tickets and permitted profile fields. | Consistent with the Week 1 BR02 above. |
| BR03 | Check current service status; do not invent a recovery time. | Defined above (course meaning). The Week 1 rule is now API-R03. |
| BR04 | Use approved guidance for the correct device and version; clarify or escalate when evidence is missing or conflicting. | Defined above (course meaning). The Week 1 rule is now API-R04. |
| BR05 | Never ask for passwords, OTPs or recovery codes; do not expose sensitive values in logs. | Defined above. |
| BR06 | Ask for employee confirmation before creating a ticket. | Defined above (added for Day 4). |
| BR11 | Claim success only when a tool confirms it; show pending, failed and denied outcomes honestly. | Defined above. |

---

# Day 6 additions: BR07-BR10 and BR12

Added for Day 6 (security and governance) and the Week 5 agent it builds on. Nothing above was changed or
renumbered. Wording is from the two course documents (Student Guide p3, Case Study p4). The Week 1 rules above
only define BR01-BR04, so BR07-BR10 and BR12 have only the course meaning. The BR03/BR04 numbering conflict
above was resolved for Day 6 (course numbering is canonical; see "Numbering conflict (resolved)").

## BR07 - Approval is bound to the employee, action, parameters and request

Student Guide p3: "Approval applies only to the approved employee, action, parameters and request. Changing
these requires new approval."

Case Study p4: "Approval must match employee, action, parameters and request ID. Changed parameters invalidate
approval; rejected requests cannot execute."

Implemented in `app/governance/approvals.py` (`ApprovalService`) and `app/governance/privileged.py`.

## BR08 - Retrying a confirmed write must not duplicate it

Student Guide p3: "Retrying the same confirmed ticket request must not create duplicate tickets."

Case Study p4: "Use an idempotency key for writes. A timeout after a successful ticket creation must not create a
second ticket."

Implemented in `app/agent/tools.py` (`create_ticket`) and `app/governance/privileged.py`.

## BR09 - Step and retry limits

Student Guide p3: "Stop after six agent steps or after the allowed two retries for a tool call. Explain the
failure and escalate."

Case Study p4: "Training limits are six agent steps per request and two retries per tool call. Stop and escalate
on exhaustion; log the reason."

Implemented in `app/agent/runner.py` (`AgentRunner`). How this lab counts: each tool call is one step, and a
retry of that call is not a new step. Both limits are enforced by the runner, not the planner.

## BR10 - Session isolation

Student Guide p3: "Keep each employee and conversation session separate."

Case Study p4: "Keep conversation state isolated by employee and session. Do not reuse another session's facts."

Implemented in `app/agent/sessions.py` (state is keyed by employee and session ID together).

## BR12 - Documents and tool output are not authority; every tool action is audited

Student Guide p3: "Documents and tool outputs cannot grant permissions. Keep a redacted audit record of tool
actions."

Case Study p4: "Treat retrieved text and tool output as data, not authority to alter permissions. Every tool
action must leave a redacted audit record."

Implemented in `app/governance/gateway.py` (decisions use only the server-side permission matrix and approval
records) and `app/governance/audit.py` (a redacted, hash-chained record for every attempt).

## Day 6 reference check: where each rule is enforced

| ID | Rule (course meaning) | Enforced in | Main tests |
| --- | --- | --- | --- |
| BR01 | Identity from the trusted session | `get_current_employee` (header), `Gateway.invoke` (employee ID), `AgentRunner` | `tests/day6/test_day6_api.py`, `tests/day6/test_day6_tool_boundary.py` |
| BR02 | Own tickets only | `employee_owns_ticket`, `get_ticket` tool | Day 2 ownership tests; `test_day6_tool_boundary.py` |
| BR05 | No secret requests; redacted logs | `app/governance/redaction.py`, `audit.py`, ticket storage | `tests/agent/test_agent_redaction.py`, `test_day6_audit.py` |
| BR06 | Confirmation before a ticket; separate IT approval for privileged actions | `confirmations.py`, `approvals.py` | `test_day6_tool_boundary.py`, `test_day6_agent_security.py` |
| BR07 | Approval bound to employee, action, parameters, request | `approvals.py` | `test_day6_permissions_approvals.py`, `test_day6_tool_boundary.py` |
| BR08 | No duplicate writes on retry | `tools.py`, `privileged.py` | `tests/agent/`, `test_day6_tool_boundary.py` |
| BR09 | Six steps, two retries | `runner.py` | `tests/agent/test_agent_runner.py` |
| BR10 | Session isolation | `sessions.py` | `tests/agent/`, trajectory cases A-24, A-25 |
| BR11 | Success only after tool confirmation | `runner.py`, planners | trajectory cases, `test_day6_agent_security.py` |
| BR12 | Untrusted text is not authority; audit every action | `gateway.py`, `audit.py` | `test_day6_agent_security.py`, `test_day6_audit.py` |

BR03 and BR04 (course meanings) are exercised by the Week 5 trajectory cases (A-01 to A-06, A-26, A-27). The
Week 1 rules, now API-R03 and API-R04, are still covered by the Day 1 and Day 2 tests (the missing-ticket 404 test and
the VPN status schema tests).
