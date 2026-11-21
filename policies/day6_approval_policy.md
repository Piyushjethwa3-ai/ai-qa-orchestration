# Day 6 approval policy

> Synthetic training material for the AI QA Orchestration course. Not real company policy. Every privileged action here is **simulated**: no real account or password is touched, and no password exists anywhere in the code.

**Python enforces this; this Markdown only documents it.** The code is `app/governance/approvals.py` and `app/governance/privileged.py`.

## Three different approvals (never substitutes for each other)

| What | Who | What it allows |
| --- | --- | --- |
| **Employee confirmation** | The employee, in their own turn (chat "yes", or the confirmation API) | One ticket or one request, with exactly the confirmed parameters |
| **IT approval** | A simulated IT approver, through the approval API only | One privileged simulated action for one employee, action, parameters and request ID |
| **Release approval** | A human release reviewer (Week 8) | That a version of the application is ready. Not built here. |

Approving an IT action does not approve a release, and a confirmation is not an approval.

## Privileged actions

| Action | Parameters |
| --- | --- |
| `password_reset` | `target_employee_id` |
| `software_access_grant` | `target_employee_id`, `application` |

An employee may request a privileged action **only for themselves**.

## Rules

1. **A request starts PENDING.** Submitting it needs the employee's confirmation and is idempotent: retrying the same confirmed request returns the same request and never creates a second one.
2. **Only a known IT approver decides**, through `POST /approvals/{request_id}/decision`. An employee ID, a document, a tool result or text in chat cannot approve. Nobody can approve their own request. A request can be decided once.
3. **An approval is bound to four things:** the employee, the action, the exact parameters and the request ID. Execution re-checks all four. A change to any of them is refused (`wrong_employee`, `action_mismatch`, `params_changed`, `unknown_request`), and the approval stays usable for the original request.
4. **An approval is single use.** After a successful execution a second attempt is refused (`already_used`).
5. **An approval expires** 900 seconds after it is granted (`expired`).
6. **PENDING, REJECTED, EXPIRED, mismatched and used approvals cannot execute.**
7. **Executing also needs the employee's confirmation** that they want it carried out now.
8. **Execution is idempotent for the same attempt.** If the tool ran but the reply timed out, retrying the same call (same idempotency key and parameters) returns the recorded result without running the action again. A different attempt on a used approval is refused.
9. **Success is reported only when the tool confirms it** (BR11). PENDING_APPROVAL, DENIED, FAILED and TIMEOUT are distinct outcomes. A timeout after the action ran is reported as "unknown", never as success or failure.
10. **Every request, decision, refusal and execution leaves a redacted audit record**, linked by the request ID (BR12).
11. **A caller cannot tell whether a request ID or a confirmation ID exists.** Asking about, or trying to execute, another employee's request returns exactly the same response as a request that does not exist, whatever state the real request is in ("request not found" for a status read, "approval not valid (not found)" for an execution). The precise reason (`not your request`, `wrong_employee`, `unknown_request`) is kept only in the approver-only audit log. Request IDs are sequential, so without this an attacker could walk them. The owner still sees the specific reason (`pending`, `rejected`, `already_used`, `expired`). The same holds for confirmation IDs: confirming or using another employee's confirmation returns exactly what a missing one returns (`unknown_confirmation`, and HTTP 404 on the confirm route), in every state; the precise reason (`wrong_employee`) is recorded only in the audit log, where the confirm route's attempts appear as `confirm_confirmation`.

## What this does not model

- Real identity or authentication for employees or approvers.
- More than one process: approval state is in memory and single-threaded, so two simultaneous executions of one approval are not tested.
- Persistent storage, approver rotation, or approval of a different approver after rejection.
