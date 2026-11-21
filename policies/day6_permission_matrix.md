# Day 6 permission matrix

> Synthetic training material for the AI QA Orchestration course. Not real company policy.

**Python enforces this; this Markdown only documents it.** The code is `app/governance/permissions.py`, applied by `app/governance/gateway.py`. If the two disagree, the code is what runs and this file needs fixing. A test (`tests/day6/test_day6_docs_match_code.py`) compares this file with the code.

## Roles

| Role | Who | How the server knows |
| --- | --- | --- |
| `employee` | A person calling the API directly | `X-Demo-Employee-ID` header |
| `agent` | The service desk agent acting for the signed-in employee | The agent runner; identity comes from the same trusted session, never from chat text |
| `it_approver` | A simulated IT approver (`data/approvers.json`) | `X-Demo-Approver-ID` header, checked against that file |

The headers are a **training stand-in for real authentication** (see the threat model). The point of this lab is what happens after identity is established.

## Operation classes

- **ALLOWED**: permitted, still limited to the caller's own records.
- **CONFIRMATION_REQUIRED**: permitted only after the employee's recorded confirmation of exactly these parameters (BR06).
- **APPROVAL_REQUIRED**: permitted only with a valid IT approval matching employee, action, parameters and request ID, **and** the employee's confirmation (BR06, BR07).
- **PROHIBITED**: never, for that role.

Anything not listed is **PROHIBITED** (default deny).

## Matrix

| Tool | Employee | Agent | IT approver |
| --- | --- | --- | --- |
| `get_service_status` | ALLOWED | ALLOWED | ALLOWED |
| `retrieve_guide` | ALLOWED | ALLOWED | ALLOWED |
| `search_tickets` | ALLOWED | ALLOWED | PROHIBITED |
| `get_ticket` | ALLOWED | ALLOWED | PROHIBITED |
| `create_ticket` | CONFIRMATION_REQUIRED | CONFIRMATION_REQUIRED | PROHIBITED |
| `request_privileged_action` | CONFIRMATION_REQUIRED | CONFIRMATION_REQUIRED | PROHIBITED |
| `execute_privileged_action` | APPROVAL_REQUIRED | APPROVAL_REQUIRED | PROHIBITED |
| `get_privileged_request_status` | ALLOWED | ALLOWED | PROHIBITED |
| `decide_approval` | PROHIBITED | PROHIBITED | ALLOWED |
| `read_audit_log` | PROHIBITED | PROHIBITED | ALLOWED |

Notes:

- `search_tickets`, `get_ticket` and `get_privileged_request_status` return **only the caller's own records**. Another employee's ticket is denied by the tool and the denial contains no ticket content (BR02).
- An IT approver cannot use the employee tools. Approving a request is not the same as executing it, and the approver cannot do both.
- `decide_approval` and `read_audit_log` have **no agent tool**. Nothing the agent, a document or a tool result says can reach them.

## Never allowed for any role

These have no tool. An attempt is still denied and written to the audit log.

- `grant_permission`
- `change_identity`
- `approve_own_request`
- `disable_audit`
- `modify_audit_record`
- `read_other_employee_ticket`

## Allowed parameters

A tool call may carry only these parameters. `employee_id` is added by the gateway from the trusted session; a different `employee_id` in the call is refused. Any other parameter (for example `approved`, `role`, `bypass`) is refused as an attempt to smuggle in authority.

| Tool | Allowed parameters |
| --- | --- |
| `get_service_status` | `service` |
| `retrieve_guide` | `query`, `os` |
| `search_tickets` | (none) |
| `get_ticket` | `ticket_id` |
| `create_ticket` | `confirmation_id`, `description`, `idempotency_key`, `subject` |
| `request_privileged_action` | `action`, `application`, `confirmation_id`, `idempotency_key`, `target_employee_id` |
| `execute_privileged_action` | `action`, `action_params`, `confirmation_id`, `idempotency_key`, `request_id` |
| `get_privileged_request_status` | `request_id` |

## Where each check runs

1. **Gateway** (`gateway.py`): default deny, role check, employee ID, parameter list, presence of a confirmation or request ID, and an audit record for every attempt.
2. **Tool** (`tools.py`, `privileged.py`): ownership, the full confirmation check, the full approval check, idempotency. The tool does not trust the gateway, so calling the tool directly cannot skip a check.

Both layers are tested. Section 3 of `docs/day6_threat_model.md` lists the tests.
