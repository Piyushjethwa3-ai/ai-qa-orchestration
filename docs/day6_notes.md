# Week 5 agent and Day 6 security and governance: notes

> Synthetic training material. The company, people and policies are fictional and every privileged action is simulated.

Day 6 (security and governance) needs something to attack, and the project had no agent, so the Week 5 agent was built first and Day 6 was built on top of it. Everything is deterministic and offline: there is **no language model, no network call and no API key** anywhere in this work.

A second pass then made it classroom-ready: stronger enforcement tests, a prompt-injection demonstration, a resolution of the BR03/BR04 numbering conflict, two training command lines, and full coverage of all twelve business rules.

## 1. What was built

**Week 5: the agent** (`app/agent/`)

| Piece | What it does |
| --- | --- |
| `tools.py` | Simulated tools: service status, guide retrieval (the Day 5 retriever, unchanged), own-ticket search and read, ticket creation. Distinct results: `SUCCESS`, `FAILED`, `TIMEOUT`, `DENIED`, `NOT_FOUND`, `PENDING_APPROVAL`. Tickets live in memory; `data/*.json` is never written. Faults are scripted for tests only. |
| `confirmations.py` | Server-side employee confirmation. A write tool refuses to run without a confirmed, unused confirmation for exactly these parameters (BR06). |
| `sessions.py` | State keyed by employee **and** session (BR10). |
| `planner.py` | Rule-based planner: status first, ask for the device, retrieve the guide, look up tickets, propose a ticket. It states only what a tool result supports (BR11). |
| `runner.py` | Enforces what must hold even if the planner is wrong: identity from the session, six steps, two retries with identical parameters, honest "unknown" on an unconfirmed write, redaction. |
| `cli.py` | `python -m app.agent` (Week 5 alone) and, through `app/governance/__main__.py`, `python -m app.governance` (Day 6): `list`, `demo NAME`, `chat`. Offline, deterministic, beginner help text. |

**Day 6: governance** (`app/governance/`, new routes in `app/main.py`)

| Piece | What it does |
| --- | --- |
| `permissions.py` | Role by tool matrix with default deny and a parameter allow-list. |
| `approvals.py` | IT approvals bound to employee, action, parameters and request ID; single use; expiry; separation of duties. |
| `privileged.py` | Simulated privileged tools. The approval check is inside the tool, so calling the backend directly cannot skip it. |
| `gateway.py` | The one place every tool call passes through. An audit record for every attempt. |
| `audit.py`, `redaction.py` | Redacted, hash-chained audit log; pattern-based redaction. |
| New routes | `POST /agent/chat`, `POST /tools/{tool}`, `POST /confirmations`, `POST /confirmations/{id}/confirm`, `POST /approvals/{id}/decision`, `GET /audit`. All additive. |

**Evaluation** (`evaluators/`)

| Piece | What it does |
| --- | --- |
| `trajectory.py` | Runs a case on a fresh stack and checks outcomes, tool sequence and statuses, parameters, retry counts, stored state, approvals, executions, evidence, prohibited tools and text, and the audit chain. A case runs on the plain agent, the governed stack, or the governed stack with the reset flow (`setup.mode`). A turn can be a chat message, an IT approver decision, a real execution attempt, a clock advance, or the set-up for the injection case. |
| `injection_demo.py` | The prompt-injection demonstration: a deliberately gullible stand-in for a model that obeys `CALL` lines hidden in a retrieved document, run against the real gateway and tools. `python -m evaluators injection-demo`. |
| `audit_example.py` | The deterministic scenario behind `docs/day6_audit_examples.md`. |

**Documents:** classroom guide (`docs/day6_demo_guide.md`), threat model, permission matrix, approval policy, audit examples, business rules (BR03/BR04 resolved, BR07 to BR10 and BR12 defined).

## 2. How to run it

The commands are identical on macOS/Linux and Windows PowerShell (activate the virtual environment first: `source .venv/bin/activate` or `.venv\Scripts\Activate.ps1`).

```bash
python -m pytest -q
python -m pytest tests/agent -v
python -m pytest tests/day6 -v
python -m evaluators trajectories
python -m evaluators injection-demo
python -m app.agent demo vpn-ticket
python -m app.governance demo privileged
```

None needs credentials or a network. The test modules block sockets and remove `OPENAI_*` variables. The classroom guide has the fresh-clone steps for both platforms. `evaluators` is registered in `pyproject.toml`; a fresh `python -m pip install -e ".[dev]"` picks it up (no new dependency).

## 3. Evidence from the verification run (2026-11-21)

Run with `env -u OPENAI_API_KEY -u OPENAI_MODEL -u OPENAI_JUDGE_MODEL python -m pytest -q`:

| Suite | Tests |
| --- | --- |
| Days 1 to 5 (unchanged) | 353 |
| `tests/agent/` (Week 5) | 122 |
| `tests/day6/` | 381 |
| **Total** | **856 passed, 0 failed, 0 skipped, no warnings** |

- **Stability:** three consecutive full runs, five random-order runs (seeds 1 to 5), a reversed directory order, and the earlier Day 6 then Day 4 then Day 3 hazard order all gave 856 passed. A fresh copy built from exactly the release file list (no virtual environment, no caches, no reports) also passes all 856, all 36 trajectories and the demonstrations. Each suite also passes on its own.
- **Trajectories:** 36 of 36 pass (A-01 to A-30 are the original Week 5 cases and are byte-for-byte unchanged; B-01 to B-06 are new). All twelve business rules are covered: BR07 by B-01 to B-04 and B-06, BR12 by A-29 and B-05. A test requires all twelve.
- **Real attempts, not set-up:** B-01 makes six actual attempts to execute the privileged action: before approval, with changed parameters, with a changed action, as another employee, and again after use. Only the one exact approved attempt runs.
- **The tests can fail.** A table of 17 mutation-style checks runs one real attack with its control ON (blocked), with ONLY that control switched off (it works), and again afterwards. Each B case also fails when its control is removed. I additionally removed 14 controls one at a time against the whole new suite: every removal made between 2 and 86 tests fail.
- **Side effects:** none. `data/`, the knowledge documents and the Day 3 to 5 datasets are byte-identical before and after (checksum compared). No new file appears in `reports/`. The new code imports no network library; the only write paths are an opt-in audit file (never used by the API or the command lines) and the evaluator report folder you name.
- These counts describe this run on this machine. They are not a claim about any other environment.

## 4. Failures found and what changed

**Earlier pass (kept for the record)**

1. *My own evaluator wrongly failed six cases.* The prohibited pattern `has been created` matched the agent's honest sentence "Nothing has been created yet". The pattern now ignores negated wording; a lying planner still fails.
2. *A secret could be stored in a ticket through the direct API.* Redaction ran in the runner, so a direct call skipped it. The ticket tool now redacts before storing.

**This pass: tests that passed for the wrong reason**

I removed each control in turn and listed the security tests that still passed. Several passed under **every** removal because the rule-based planner simply never attempts a prohibited action, so they showed the planner's behaviour and not the enforcement:

- the poisoned-document tests (Day 6 and Week 5), the five "approval claimed in chat" cases, the rejected-request and approval-expiry tests (they read a status and never tried to execute), and an identity test with a vacuous clause (`... or len(stack.backend.tickets) == 6`: the seeded last ticket belongs to EMP002, so the `or` was what made it pass).

All were replaced. The new versions use a planner that really attempts the action, and each now fails when its control is removed (verified by the same removals). The rejected and expired tests now make an actual execution attempt.

**This pass: what the new mutation checks taught us.** Four of the first 17 mutation checks failed, which is what they are for:

- *Approval binding overlap.* The binding hash covers request ID, employee, action and parameters, and there are also explicit employee and action checks. Removing only one leaves the other blocking. This is deliberate defence in depth, so a real test of "bound to the employee" removes both.
- *Session isolation.* The victim (EMP001) already has an open VPN ticket, so there was never a proposal to steal and the attack "failed" even with isolation removed. The victim is now EMP002.
- *Approver identity.* The test had the employee approve their own request, which separation of duties blocks first. A different employee now tries.
- *Test helper.* With confirmation validation switched off, the tool later tried to consume an unknown confirmation and failed with a `KeyError`. That cannot happen in real runtime (validation always runs first), so the test-only helper switches both off.

**Release pass: privileged-request existence disclosure (fixed).**
*What happened.* Asking about, or trying to execute, another employee's privileged request was refused with different wording and a different status from a request that does not exist (`not your request` / 403 versus `request not found` / 404, and `wrong_employee` versus `unknown_request`). Request IDs are sequential, so an attacker could walk `PRV-0001`, `PRV-0002` ... and learn which exist.
*Why.* Each refusal reported its own precise reason straight to the caller.
*What changed.* Both cases now return the same response in every state of the real request (`request not found`, or `approval not valid (not found)`). The precise reason moved to a new internal field that only the approver-only audit log receives. The owner still sees the specific reasons (`pending`, `rejected`, `already_used`, `expired`).
*How it was verified.* 29 regression tests (`tests/day6/test_day6_existence.py`) compare a foreign request with a missing one in all five states, through the gateway and over HTTP, plus malformed IDs; check that the owner keeps the specific reason, that the audit log keeps the truth, and that the internal reason never reaches a caller, the agent trace or the CLI. Two tests prove the comparison would notice if the leak came back, and the new tests also **fail against the original behaviour** (checked by restoring the old handlers in a scratch run). Two expectations that asserted the old wording were updated on purpose (case B-01's fourth denial reason, now `not found`, and one refusal-reason check).
*Then extended to confirmation IDs* (next paragraph).

**Release pass: confirmation-ID existence disclosure (fixed).**
*What happened.* Confirming or using another employee's confirmation was refused differently from a confirmation that does not exist: HTTP 403 versus 404 on `/confirmations/{id}/confirm`, and `wrong_employee` versus `unknown_confirmation` in a tool refusal. Confirmation IDs are sequential (`CONF-0001` ...), so they could be walked.
*Why.* The store reported the precise reason straight to the caller, and the route turned it into different status codes.
*What changed.* Both cases now raise the same `unknown_confirmation` in every state of the real confirmation, so the route answers 404 and the tools answer `confirmation required (unknown_confirmation)` for both. The exception carries the precise reason in a separate internal field, which the gateway writes to the approver-only audit log. The confirm route previously wrote no audit record at all; it now records each attempt as `confirm_confirmation` (denied with the precise reason, or allowed), so an investigator can still see the truth. The owner is unaffected: a valid confirmation still works, a repeated yes is harmless, and the owner still sees `already_used`, `cancelled`, `not_confirmed`, `action_mismatch` and `params_changed`.
*How it was verified.* 44 regression tests (`tests/day6/test_day6_confirmation_existence.py`) compare a foreign confirmation with a missing one in all four states (proposed, confirmed, consumed, cancelled) at the store, through all three confirmation-consuming tools, and over HTTP; they also cover malformed IDs, the owner's preserved behaviour, the audit trail, and that the internal reason never reaches a caller, the agent trace or the CLI. **Against the original behaviour 34 of them fail** (restored in a scratch plugin; no repo file was edited), and all 44 pass on the fixed code. Three older expectations that asserted the old wording or the 403 were updated on purpose (two store-level tests in `tests/agent/test_agent_tools.py` and one HTTP test).

**Release pass: other changes.** A student handoff checklist (`docs/day6_student_checklist.md`) whose test count, trajectory count, commands, paths and "look for" lines are checked by tests. A new test file reused the last four characters of a masked key that already appears in a committed Day 3 test; the new file now uses an obviously fake suffix. The Day 3 test was not touched.

**Pre-existing, not changed:** `tests/day5/test_day5_faults.py:85` opens a file without closing it. It raises a `ResourceWarning` that only becomes a failure when warnings are treated as errors (`-W error`). It reproduces with only the Day 1 to 5 suites, so it predates this work. A normal run shows no warnings.

## 5. Decisions and assumptions to review

- **BR03 and BR04 are resolved: the course catalogue is canonical.** The two Week 1 rules are now **API-R03** (a missing ticket returns 404) and **API-R04** (VPN status has a status and update time); their text, tests and meaning are unchanged. Their headings start `## API-R`, which the Day 3 and Day 4 tools ignore, so each ID is discovered exactly once with its course meaning. The Day 1 and Day 2 files that still say "BR03" or "BR04" in the Week 1 sense are listed in an alias table in `docs/business_rules.md` and were not edited; two docstrings in `app/main.py` now use the new labels (this changes the text FastAPI shows in its generated docs, not behaviour). **The project owner confirmed this mapping on 2026-11-21.** All 212 Day 1 to 4 tests and the Day 3 and Day 4 rule discovery still pass.
- **Counting for BR09:** each tool call is one step, and a retry of that call is not a new step. The Student Guide does not define this.
- **Roles:** `employee`, `agent` and `it_approver`. The Case Study mentions "three permission roles" without naming them.
- **Two privileged actions** (`password_reset`, `software_access_grant`). The agent drives only the reset.
- **Executing a privileged action needs both** IT approval and the employee's confirmation that it should run now.
- **A timeout after the action ran is reported as "unknown"**, never as success or failure, and retrying the same call returns the recorded result instead of running the action again.
- **The injection demo raises the step budget from 6 to 10** (and says so in its output) so the stand-in can attempt every instruction. At the normal limit BR09 stops it after four attempts.
- **The tickets the agent creates are in memory only.** The Week 1 API reads `data/tickets.json`, so `GET /tickets/TCK-1007` returns 404 for an agent ticket. This is documented in the CLI output, the README and the guide. Persistence was not changed.
- **Not expanded:** the Case Study proposes 12 employees, 20 tickets and 12 knowledge documents. The project still has 4, 6 and 8.

## 6. What this does not show

No language model was involved, so nothing here shows how a real model resists prompt injection. The injection demonstration uses a stand-in that is deliberately gullible, and the poisoned text arrives through a test fixture, not a live document. Identity is a training header. State is in memory and single-threaded, so concurrent approval use is not tested. Redaction is pattern based and misses an unlabelled bare secret (a test records that). The audit hash chain makes edits detectable, not impossible. Request and confirmation IDs are sequential, so they are guessable; a guess gives a non-owner nothing (see section 4). The Windows PowerShell HTTP examples in the classroom guide were **not executed**, because PowerShell is not installed on the machine that wrote them; the command-line demonstrations (`python -m ...`) are identical on every platform and are the verified path. See section 5 of `docs/day6_threat_model.md` for the full list.

The Student Guide's classroom gate ("zero observed cross-user disclosures, unauthorised actions or duplicate writes") holds for these tests on this code. It is not a safety claim about a production system.

## 7. Changed files

Tracked files edited: `README.md` (new section; Business rules paragraph), `docs/business_rules.md` (BR03/BR04 resolution and appended BR07 to BR10, BR12 and the Day 6 table), `app/main.py` (new routes after the existing ones; two docstrings relabelled), `pyproject.toml` (registers `evaluators`).

New: `app/agent/`, `app/governance/`, `app/runtime.py`, `data/approvers.json`, `evaluators/`, `datasets/agent/`, `policies/day6_*.md`, `docs/day6_*.md` (including the demo guide and the student checklist), `tests/agent/`, `tests/day6/`.

Nothing was committed or pushed.
