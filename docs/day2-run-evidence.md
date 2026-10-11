# Day 2 Run Evidence

Sanitised evidence for the Day 2 submission. Every result below was
produced by actually running the commands on 2026-10-03 against this
repository — not copied from a lesson plan.

**Sanitisation note:** absolute paths have been replaced with
`<project-root>` throughout, and no raw report file is committed. The
generated `reports/` directory is git-ignored because the JSON report
embeds the local absolute project path (which contains an OS account
name). See [Secrets and sanitisation review](#secrets-and-sanitisation-review).

## 1. Environment

| Item | Value |
| --- | --- |
| Python | 3.11.0 (project pins `>=3.11,<3.13`) |
| pytest | 8.4.2 |
| fastapi | 0.141.1 |
| httpx | 0.28.1 |
| jsonschema | 4.26.0 |
| uvicorn | 0.54.0 |
| pytest-html | 4.2.0 |
| pytest-json-report | 1.5.0 |
| pytest-metadata | 3.1.1 (transitive) |
| Virtual environment | `.venv/` at the project root, git-ignored |
| API server needed for tests | No — `TestClient` runs the app in-process |

## 2. Actual test results

All commands run from the project root with `.venv` active.

### Day 1 only

```
python -m pytest tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
7 passed, 1 warning
```

### Day 2 only

```
python -m pytest tests/day2 -v
14 passed, 1 warning
```

### Full suite (final baseline)

```
python -m pytest -v
21 passed, 1 warning
```

Breakdown of the 21:

| File | Tests | Purpose |
| --- | --- | --- |
| `tests/test_tickets.py` | 4 | Day 1 baseline: own ticket 200, foreign ticket 403, schema, missing ticket 404 |
| `tests/test_employees.py` | 1 | Day 1 baseline: `/employees/me` happy path |
| `tests/test_service_status.py` | 2 | Day 1 baseline: `/health`, VPN status (BR04) |
| `tests/day2/test_01_fixtures.py` | 2 | Fixtures: Employee A and Employee B each read their own ticket |
| `tests/day2/test_02_parameterized.py` | 5 | Parametrization: 2×200, 2×403 (both directions), 1×404 |
| `tests/day2/test_03_ownership.py` | 2 | BR02 both directions + denial-body leak check |
| `tests/day2/test_04_schema.py` | 5 | 4 real API response schemas + 1 non-API beginner example |

The one warning in every run is a pre-existing Starlette deprecation
notice about `httpx`/`httpx2`, emitted on import of
`fastapi.testclient`. It is unrelated to any test's correctness and
predates Day 2.

## 3. Unique API coverage

"Unique" means distinct (endpoint, condition, expected status)
combinations actually exercised over HTTP. Repeats that exist for
teaching reasons are listed but not counted twice.

| # | Endpoint | Condition | Status | Where verified |
| --- | --- | --- | --- | --- |
| 1 | `GET /health` | always | 200 | `test_service_status.py` |
| 2 | `GET /employees/me` | valid header | 200 | `test_employees.py`, `test_04_schema.py` |
| 3 | `GET /services/vpn/status` | always | 200 | `test_service_status.py`, `test_04_schema.py` |
| 4 | `GET /tickets/{id}` | own ticket | 200 | `test_tickets.py`, `test_01_fixtures.py`, `test_02_parameterized.py`, `test_04_schema.py` |
| 5 | `GET /tickets/{id}` | another employee's ticket | 403 | `test_tickets.py`, `test_02_parameterized.py`, `test_03_ownership.py` |
| 6 | `GET /tickets/{id}` | well-formed id, no such ticket | 404 | `test_tickets.py`, `test_02_parameterized.py`, `test_04_schema.py` |

**Unique API conditions covered: 6.** Total test items: 21 — the gap is
deliberate repetition across lessons (the same scenario taught first
concretely, then parametrized, then schema-validated).

Explicitly **not** counted as API coverage:

- `test_04_schema.py::test_beginner_schema_example_missing_required_field`
  validates a hand-built dict, makes no HTTP call, and is labelled as a
  teaching aid in its own docstring.
- The two 200 cases in `test_02_parameterized.py` repeat
  `test_01_fixtures.py`'s employee/ticket pairs on purpose, to
  demonstrate parametrization on an already-trusted case.

### Known coverage gaps (not yet tested anywhere)

- `GET /employees/me` and `GET /tickets/{id}` with a **missing**
  `X-Demo-Employee-ID` header → documented as 400, but not currently
  asserted by any committed test. (An earlier provisional draft covered
  it; the lesson-by-lesson rewrite scoped it out and it has not been
  reinstated.)
- Same two endpoints with an **unknown** employee id → documented as
  400, also not currently asserted.
- Employees `EMP003` / `EMP004` and tickets `TCK-1003`–`TCK-1006` appear
  in fixtures and tables but are no longer exercised by a committed
  200-path test after the Day 2 rewrites.
- `GET /services/vpn/status` is only ever observed in its
  `operational` state; `degraded` and `outage` are allowed by the schema
  and BR04 but never produced by the fixture data.

## 4. Code and data under test

### Application code

| File | What it contributes |
| --- | --- |
| `app/main.py` | 4 routes + `get_current_employee` (the header-based identity dependency). Enforces BR01 (400s), BR02 (403), BR03 (404). |
| `app/rules.py` | `find_employee_by_id`, `find_ticket_by_id`, `employee_owns_ticket`. `employee_owns_ticket` is the single ownership decision point (BR02). |
| `app/data.py` | Reads the JSON files in `data/`. No caching — each call re-reads from disk. |

### Fixture data (synthetic, no real people)

- `data/employees.json` — 4 employees: `EMP001` Dana Whitfield
  (Finance), `EMP002` Marcus Lee (Sales), `EMP003` Priya Nair
  (Engineering), `EMP004` Oliver Grant (Human Resources). Emails use the
  reserved `@northstar.example` domain.
- `data/tickets.json` — 6 VPN tickets. Ownership: `EMP001` →
  `TCK-1001`, `TCK-1005`; `EMP002` → `TCK-1002`, `TCK-1006`; `EMP003` →
  `TCK-1003`; `EMP004` → `TCK-1004`.
- `data/service_status.json` — one VPN status record, currently
  `operational`.

All three files are read-only for the entire test suite. No test, and
no fault injection, writes to `data/`. Verified by re-reading the files
after the fault runs — unchanged.

### Contract files

`schemas/ticket.schema.json` (pre-existing), plus
`schemas/employee.schema.json`, `schemas/service_status.schema.json`,
and `schemas/error.schema.json` added for Day 2. Validation is applied
through the reusable `validate_against_schema` fixture in
`tests/day2/conftest.py`.

## 5. Fault-injection evidence

The `--day2-fault` option is **test-only and off by default**
(`default=None`). Verified facts:

- `grep -rn "fault" app/` returns no fault logic in the application
  package (the only textual match is the unrelated word `default` in a
  `Header(default=None, ...)` call).
- Fault code exists in exactly three files, all under `tests/`:
  `tests/conftest.py` (option registration only),
  `tests/day2/test_03_ownership.py`, `tests/day2/test_04_schema.py`.
- Each fault is applied by a **file-scoped `autouse` fixture** using
  pytest's built-in `monkeypatch`, which reverts automatically after
  every test, on pass, fail, or error.
- Faults are injected in the application's own response-generation path
  (`app.rules.employee_owns_ticket`, `app.data.load_service_status`),
  not by editing a response object inside a test.
- A real running API (`uvicorn app.main:app`) cannot be affected — that
  process never imports pytest or these fixtures.

### Observed fault results

| Flag | Command | Observed |
| --- | --- | --- |
| `ownership` | `pytest tests/day2/test_03_ownership.py --day2-fault=ownership -v` | **2 failed** — both with `assert 200 == 403` |
| `missing-status` | `pytest tests/day2/test_04_schema.py --day2-fault=missing-status -v` | **1 failed, 4 passed** — `ValidationError: 'status' is a required property` |
| `wrong-status-type` | `pytest tests/day2/test_04_schema.py --day2-fault=wrong-status-type -v` | **1 failed, 4 passed** — `ValidationError: 1 is not of type 'string'` |

Isolation check — the full suite run with each flag produced failures
**only** in the targeted file; every other test kept passing. Notably
Day 1's `test_vpn_status_has_defined_status_and_update_time`, which
reads the same `status` field but lives in a different file, kept
passing under both status faults.

Recovery check — re-running each file with no flag returned it to
all-passing, in the same shell session.

### Did the framework catch the schema faults first?

No, and this was checked rather than assumed. Neither route declares a
`response_model=`; both use a bare `-> dict` return annotation, which
FastAPI does not treat as an output contract. Both malformed payloads
(a dict missing a key; an int where a string belongs) are ordinary
JSON-serialisable values, so the server returned a normal `200 OK` with
the malformed body in both runs. `jsonschema`, invoked explicitly by
the test file, was the only layer that caught either fault.

If `response_model=` is ever added to `get_vpn_status`, this finding
needs re-verification — Pydantic could then reject these payloads
before the response is sent.

## 6. Report generation

```
python -m pytest -v --html=reports/day2-report.html --self-contained-html \
  --json-report --json-report-file=reports/day2-report.json
```

Result: `21 passed, 1 warning`; both files written to `reports/`
(`day2-report.html` ≈ 46 KB, `day2-report.json` ≈ 14 KB).

## 7. Secrets and sanitisation review

Audited both generated reports before deciding what to commit:

| Check | Result |
| --- | --- |
| API keys / tokens / passwords / bearer / authorization strings | **None found** in either report |
| Email addresses | **None found** |
| Real personal data | None — all employee records are synthetic, using the reserved `.example` domain |
| Local absolute path (contains an OS account name) | **Found once**, in the JSON report's `root` field |
| Platform/machine metadata | Present in pytest's own header output (OS build string, package list) |

Actions taken:

- `reports/` stays git-ignored, so neither raw report is committed.
- This document quotes only summary lines and sanitised excerpts, with
  absolute paths replaced by `<project-root>`.
- `.gitignore` hardened to also cover `.env.*` variants (e.g.
  `.env.local`) and `*.log`, while keeping `.env.example` tracked via
  the existing negation rule.
- `.env.example` reviewed: contains only `APP_ENV=development` and
  explanatory comments. No credentials. Safe to keep tracked.

Verified ignored (via `git check-ignore`): `.venv`, `reports/`,
`reports/day2-report.html`, `reports/day2-report.json`, `.env`,
`.pytest_cache`, `app/__pycache__`, `.DS_Store`,
`northstar_service_desk.egg-info`.

## 8. Limitations

1. **Identity is not authentication.** `X-Demo-Employee-ID` is an
   unverified header. Anyone can claim any employee id. Nothing in this
   project should be read as evidence of a working access-control
   system — BR02 only prevents *cross-employee reads given an honest
   header*.
2. **Coverage gaps listed in section 3** — notably the BR01 400 cases
   (missing and unknown header) are documented but currently
   unasserted.
3. **Read-only API.** Only `GET` endpoints exist, so there is no
   coverage of create/update/delete, validation of request bodies, or
   any state transition.
4. **Static fixture data.** The VPN status never leaves `operational`,
   so `degraded`/`outage` branches of the schema and BR04 are untested.
5. **`format: "date-time"` is not enforced.** `jsonschema` treats
   `format` as an annotation unless a format checker is supplied, and
   none is. A malformed `created_at`/`updated_at` string would pass
   schema validation today.
6. **Single-process, sequential assumption.** Fault isolation relies on
   pytest running tests one at a time. Under `pytest-xdist` or any
   parallel runner, a monkeypatched module could overlap with another
   worker's test. The faults were not tested under parallel execution.
7. **Local-only verification.** All results come from one machine
   (macOS, Python 3.11.0). There is no CI workflow, so nothing has been
   verified on Windows, on Linux, or on another Python patch version.
8. **`reports/` is not reproducible evidence.** Because it is
   git-ignored, a reviewer must regenerate reports locally; this
   document is the committed substitute.
9. **Installed-vs-declared drift is now fixed but worth noting.**
   `pytest-html` and `pytest-json-report` were present in the local
   `.venv` before being declared in `pyproject.toml`; they are declared
   as of this submission, but anyone who set up the project earlier must
   re-run `python -m pip install -e ".[dev]"`.
