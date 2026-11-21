# Day 6 threat model: identity, documents, tools, session state and logs

> Synthetic training material. The company, people and policies are fictional, and every privileged action is simulated.

This threat model covers the five areas the Case Study asks for. It states what is **enforced in code**, where, which **test** shows it, and what risk **remains**. A test name here is checked by `tests/day6/test_day6_docs_match_code.py`, so a rename that leaves this file stale fails the suite.

## 1. Scope and honest assumptions

- The agent is **rule-based Python with no language model**. This lab tests the controls around the agent. It does not show how a real model would behave, and a passing run says nothing about prompt injection resistance of a model.
- Identity is a **training header** (`X-Demo-Employee-ID`, `X-Demo-Approver-ID`), not real authentication. Anyone who can send a request can set it. Everything below assumes identity is established correctly and tests what the system does next.
- State (sessions, confirmations, approvals, the audit log) is **in memory, single-process and single-threaded**.
- The question this answers is the course's: *where is a restricted action blocked if the model asks to perform it anyway?* Answer: at the **tool boundary**, in two places (the gateway, then the tool itself).

## 2. Assets and trust boundaries

| Asset | Why it matters |
| --- | --- |
| Employee tickets | Cross-user disclosure is a critical failure (BR02) |
| Privileged actions (simulated reset, access grant) | An unapproved or tampered action is a critical failure (BR06, BR07) |
| Approval records | If forged or replayed, the control is void |
| Secrets typed by employees | Must not reach logs, tickets or traces (BR05) |
| Audit log | Evidence; must show every attempt and resist quiet edits (BR12) |

**Untrusted:** chat text, retrieved document text, tool output, request bodies, header values until checked. **Trusted decisions** come only from the server-side permission matrix, the confirmation store and the approval store.

## 3. Threats, controls and evidence

| ID | Area | Threat | Control (enforced in) | Evidence (test) | Residual risk |
| --- | --- | --- | --- | --- | --- |
| T1 | Identity | Chat says "I am EMP002" | Identity is the session argument, never parsed from text (`runner.py`, `gateway.py`) | `tests/day6/test_day6_api.py::test_identity_cannot_be_changed_by_the_request_body_or_chat_text` | Header is spoofable in this lab |
| T2 | Identity | A tool call names a different `employee_id` | Gateway refuses a mismatch (`gateway.py`) | `tests/day6/test_day6_tool_boundary.py::test_acting_as_another_employee_in_the_parameters_is_refused_and_audited` | None known |
| T3 | Identity | Employee reads another employee's ticket | Ownership in the tool; denial returns no content (`tools.py`) | `tests/day6/test_day6_tool_boundary.py::test_cross_user_ticket_read_is_denied_at_the_tool_and_leaks_nothing` | Day 1 API returns 403 vs 404, so ticket existence is visible there (unchanged Week 1 behaviour) |
| T4 | Documents | A retrieved document says "approve this" or "you are an admin" | Documents are data; decisions never read them (`planner.py`, `gateway.py`) | `tests/day6/test_day6_injection.py::test_with_enforcement_every_attempt_is_refused_and_nothing_changes`, `tests/day6/test_day6_injection.py::test_with_enforcement_disabled_the_same_demo_succeeds_and_then_enforcement_is_back` | Shown with a gullible stand-in for a model, not a real model. A real model could be talked into asking; the gateway and tools would still refuse |
| T5 | Documents | Poisoned text makes the agent create a ticket | Writes need a recorded confirmation (`confirmations.py`) | `tests/agent/test_agent_runner.py::test_a_planner_that_obeys_poisoned_retrieved_text_is_still_stopped_by_the_tools` | None known |
| T6 | Tools | Direct call skips the agent and the confirmation | Gateway and tool both demand a matching confirmation | `tests/day6/test_day6_tool_boundary.py::test_direct_ticket_creation_needs_a_recorded_confirmation` | None known |
| T7 | Tools | Direct call runs a privileged action with no approval | Gateway, then the tool, check the approval | `tests/day6/test_day6_tool_boundary.py::test_direct_execution_without_approval_is_denied_by_gateway_and_by_the_tool` | None known |
| T8 | Tools | Forged or foreign request ID | Approval store lookup bound to the employee | `tests/day6/test_day6_tool_boundary.py::test_a_made_up_or_foreign_request_id_cannot_execute` | None known |
| T9 | Tools | "My manager approved" typed in chat | Only `decide_approval` approves, and it has no agent or employee path | `tests/day6/test_day6_agent_security.py::test_a_planner_that_acts_on_an_approval_claim_in_chat_is_stopped_at_the_boundary` | None known |
| T10 | Tools | Parameters changed after approval | Binding hash over employee, action, parameters, request ID (`approvals.py`) | `tests/day6/test_day6_tool_boundary.py::test_changed_parameters_after_approval_are_refused_then_the_original_still_works` | None known |
| T11 | Tools | Approval for one action reused for another | Action is part of the binding | `tests/day6/test_day6_tool_boundary.py::test_changed_action_after_approval_is_refused` | None known |
| T12 | Tools | Approval replayed for another employee | Employee is part of the binding | `tests/day6/test_day6_tool_boundary.py::test_a_valid_approval_replayed_for_another_employee_is_refused` | None known |
| T13 | Tools | Approval reused after success | Single use (`mark_used`) | `tests/day6/test_day6_tool_boundary.py::test_a_used_approval_cannot_execute_a_second_time` | Concurrent double execution is not modelled |
| T14 | Tools | Rejected or expired approval executes | Status and expiry checked at execution | `tests/day6/test_day6_tool_boundary.py::test_rejected_and_expired_approvals_cannot_execute` | Expiry uses the server clock |
| T15 | Tools | Authority smuggled in as parameters (`approved`, `role`) | Parameter allow-list per tool (`permissions.py`) | `tests/day6/test_day6_tool_boundary.py::test_authority_cannot_be_smuggled_in_as_parameters` | None known |
| T16 | Tools | Operation with no tool (`grant_permission`) | Default deny; always-prohibited list | `tests/day6/test_day6_tool_boundary.py::test_prohibited_and_unknown_operations_are_denied_for_employees_and_the_agent` | None known |
| T17 | Tools | IT approver also executes (no separation) | Approvers have no employee tools | `tests/day6/test_day6_tool_boundary.py::test_an_it_approver_cannot_use_employee_tools` | One approver could still approve a request they influenced (no four-eyes rule) |
| T18 | Tools | Retry duplicates a write | Idempotency keys (`tools.py`, `privileged.py`) | `tests/agent/test_agent_tools.py::test_same_idempotency_key_never_creates_a_second_ticket`, `tests/day6/test_day6_tool_boundary.py::test_a_retry_after_a_timeout_never_executes_twice_but_a_new_attempt_is_refused` | Keys are per process |
| T19 | Tools | Runaway loop or endless retries | Six steps, two retries, enforced by the runner | `tests/agent/test_agent_runner.py::test_step_limit_is_enforced_by_the_runner_not_the_planner`, `tests/agent/test_agent_runner.py::test_retry_limit_is_two_retries_with_identical_parameters` | No rate limit across requests |
| T20 | Session state | One employee's session leaks into another's | State keyed by employee and session (`sessions.py`) | `tests/agent/test_agent_runner.py::test_sessions_are_isolated_by_employee_and_by_session_id` | A session ID is not secret; isolation relies on the employee identity too |
| T21 | Session state | Secrets kept in conversation memory | Text is redacted before it is stored (`runner.py`) | `tests/agent/test_agent_runner.py::test_secrets_are_redacted_from_history_trace_and_reply` | Pattern based; see T23 |
| T22 | Logs | Audit log misses a denied attempt | Gateway writes a record for every attempt | `tests/day6/test_day6_audit.py::test_every_attempt_is_recorded_allowed_or_denied` | Calls made directly to the backend object (not the API) are not audited |
| T23 | Logs | A secret is written to the log or a ticket | Redaction before storage (`redaction.py`, `audit.py`, `tools.py`) | `tests/day6/test_day6_audit.py::test_secrets_in_parameters_and_errors_are_redacted_before_storage`, `tests/day6/test_day6_agent_security.py::test_secrets_typed_in_chat_never_reach_the_audit_log_or_tickets` | An unlabelled bare secret is not detected (`tests/agent/test_agent_redaction.py::test_known_limit_an_unlabelled_secret_is_not_detected`) |
| T24 | Logs | A record is edited or deleted | Hash chain, `verify_chain()` | `tests/day6/test_day6_audit.py::test_editing_a_record_is_detected`, `tests/day6/test_day6_audit.py::test_deleting_a_record_is_detected` | Someone who rewrites the whole file can recompute the chain (`tests/day6/test_day6_audit.py::test_known_limit_a_chain_can_be_recomputed_by_someone_who_rewrites_the_whole_file`); real systems need write-once storage |
| T25 | Logs | Request, approval and result cannot be linked | Shared correlation ID | `tests/day6/test_day6_agent_security.py::test_full_approved_journey_links_request_approval_and_result_in_the_audit_log` | None known |
| T26 | Logs | Employees or the agent read the audit log | Approver-only endpoint | `tests/day6/test_day6_api.py::test_only_approvers_read_the_audit_log_and_the_chain_is_intact` | None known |
| T27 | Approvals | Anyone but an approver decides | Approver ID checked against `data/approvers.json` | `tests/day6/test_day6_api.py::test_only_an_it_approver_can_decide` | Approver header is spoofable in this lab |
| T28 | Documents | A retrieved document hides `CALL` instructions that a model obeys (approve, execute, create a ticket, read another employee's ticket, act as someone else) | Every call goes through the gateway and the tools, which decide from server-side records only | `tests/day6/test_day6_injection.py::test_the_gullible_planner_really_attempts_every_prohibited_action`, `tests/day6/test_day6_injection.py::test_the_approval_check_alone_stops_the_injected_execution` | Demonstrated with a stand-in, not a real model; the injection arrives through a test fixture, not a live document |
| T29 | Tools | A refusal leaks protected data (another employee's ticket, the approver's ID or reason) | Denials carry no data; wording does not reveal whether a ticket exists | `tests/day6/test_day6_enforcement.py::test_attack_is_refused_with_a_reason_and_exposes_nothing`, `tests/day6/test_day6_enforcement.py::test_http_denials_do_not_expose_protected_data`, `tests/day6/test_day6_existence.py::test_executing_someone_elses_request_is_identical_to_executing_a_missing_one`, `tests/day6/test_day6_existence.py::test_reading_someone_elses_request_is_identical_to_reading_a_missing_one`, `tests/day6/test_day6_confirmation_existence.py::test_over_http_confirming_someone_elses_confirmation_is_identical_to_a_missing_one`, `tests/day6/test_day6_confirmation_existence.py::test_every_tool_gives_the_same_refusal_for_someone_elses_confirmation_as_for_a_missing_one` | Fixed for privileged requests and for confirmation IDs: another employee's and a missing one return the same response in every state, over the gateway and HTTP. IDs remain sequential (guessable) but a guess gives a non-owner nothing |

## 4. Would the tests notice if a control were removed?

A test that cannot fail proves nothing, so the controls are checked in three ways.

1. **Mutation-style table** (`tests/day6/test_day6_enforcement.py::test_attack_is_blocked_with_the_control_and_works_without_it`). For 17 controls, one real attack is run with the control ON (it must be blocked), then with ONLY that control switched off by a test-only monkeypatch (it must now WORK), then again afterwards (the control must be back). The controls are: each approval rule (pending, rejected, single use, expiry, employee, action, parameters), employee confirmation, ticket ownership, the permission matrix, the parameter allow-list, the gateway's employee ID check, the approver identity check, audit redaction, ticket redaction, session isolation and duplicate-write protection.
2. **Governance trajectory cases** (`tests/day6/test_day6_enforcement.py::test_governance_trajectory_case_fails_when_its_control_is_removed`). Each case B-01 to B-06 passes normally and FAILS when its control is removed.
3. **Week 5 behaviours** (`tests/agent/test_agent_trajectories.py`). The evaluator is shown to fail when duplicate writes, broken ownership, a missing step or retry limit, broken session isolation, missing redaction or a lying planner are seeded.

**What the mutation checks taught us (kept, not hidden).** Three attacks first passed for the wrong reason and were redesigned so each isolates one control. The approval binding hash covers request ID, employee, action and parameters, and there are also explicit employee and action checks. They overlap on purpose, so removing only one still leaves the other blocking; a real test of "bound to the employee" removes both. A session-isolation attack used a victim (EMP001) who already had an open VPN ticket, so there was no proposal to steal and the attack "failed" even with isolation removed. A test of "an employee cannot approve" had the employee approve their own request, which a separate separation-of-duties rule blocks first.

**Never disabled in the application.** The switches used by these tests exist only inside `tests/day6/day6_support.py`, apply to one test, and are undone by pytest. `tests/day6/test_day6_injection.py` checks that no application function takes an enforce/disable/skip/bypass parameter and that the application reads no environment variable.

## 5. Not covered (so do not claim it)

Real authentication and TLS; rate limiting; concurrency and race conditions; durable storage; write-once audit storage; behaviour of a real language model (prompt injection resistance, jailbreaks, refusals); denial of service; clock tampering; approver collusion; and any live or networked test. The classroom gate in the Student Guide ("zero observed cross-user disclosures, unauthorised actions or duplicate writes") is a statement about **these tests on this code**, not a safety claim about production.
