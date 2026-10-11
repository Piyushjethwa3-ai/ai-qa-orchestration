# Day 2 Instructor Map

Prepared by inspecting the repository as it actually exists on
2026-09-27 (branch `main`, commit `64f4caf`, working tree clean, up to
date with `origin/main`). Nothing below is assumed — every path, ID,
and status code was read from the current files or from a live test
run, not carried over from earlier lesson plans.

## 1. Exact files to open during the lesson

In this order:

1. [`app/main.py`](../app/main.py) — the 4 routes and the
   `get_current_employee` dependency (the identity mechanism).
2. [`app/rules.py`](../app/rules.py) — `find_employee_by_id`,
   `find_ticket_by_id`, `employee_owns_ticket`. This is the file Day 2's
   parametrized and ownership tests will exercise most.
3. [`app/data.py`](../app/data.py) — how the JSON files get loaded.
4. [`data/employees.json`](../data/employees.json),
   [`data/tickets.json`](../data/tickets.json),
   [`data/service_status.json`](../data/service_status.json) — the
   fixture data itself.
5. [`schemas/ticket.schema.json`](../schemas/ticket.schema.json) — the
   contract used in the schema test.
6. [`tests/conftest.py`](../tests/conftest.py) — the single `client`
   fixture every test uses.
7. [`tests/test_tickets.py`](../tests/test_tickets.py) — today's
   richest file: ownership, schema validation, and a 404 case.

## 2. Actual identity mechanism

There is no login, token, or session. Every protected route depends on
`get_current_employee()` in `app/main.py` (lines 27–51), which:

1. Reads the `X-Demo-Employee-ID` request header.
2. Returns `400` with `"Missing required header: X-Demo-Employee-ID"`
   if the header is absent or empty.
3. Loads `data/employees.json` and looks for a matching
   `employee_id`.
4. Returns `400` with `"Unknown demo employee id: {id}"` if no match.
5. Otherwise returns the matching employee dict, which the route then
   uses.

This is intentionally not real authentication — say so explicitly to
students, since it's easy to mistake a header check for a security
control.

## 3. Employee / ticket ownership table (from the actual JSON files)

| Employee ID | Name | Department | Tickets owned |
| --- | --- | --- | --- |
| `EMP001` | Dana Whitfield | Finance | `TCK-1001` (open), `TCK-1005` (in_progress) |
| `EMP002` | Marcus Lee | Sales | `TCK-1002` (resolved), `TCK-1006` (resolved) |
| `EMP003` | Priya Nair | Engineering | `TCK-1003` (in_progress) |
| `EMP004` | Oliver Grant | Human Resources | `TCK-1004` (open) |

For the recap and for cross-ownership demos, the two simplest employees
to use are **EMP001 owning TCK-1001** and **EMP002 owning TCK-1002**
— asking for EMP001's ticket while sending `EMP002`'s header is the
existing 403 test's exact scenario.

## 4. Status code and response contracts (verified against the running code)

| Route | Condition | Status | Body |
| --- | --- | --- | --- |
| `GET /health` | always | 200 | `{"status": "ok", "service": "northstar-it-service-desk"}` |
| `GET /employees/me` | header missing | 400 | `{"detail": "Missing required header: X-Demo-Employee-ID"}` |
| `GET /employees/me` | header unknown | 400 | `{"detail": "Unknown demo employee id: <value>"}` |
| `GET /employees/me` | header valid | 200 | the matching employee object |
| `GET /services/vpn/status` | always | 200 | `data/service_status.json` verbatim |
| `GET /tickets/{id}` | header missing/unknown | 400 | same as above (shared dependency) |
| `GET /tickets/{id}` | ticket id not found | 404 | `{"detail": "Ticket not found: <id>"}` |
| `GET /tickets/{id}` | ticket exists, different owner | 403 | `{"detail": "You may not view another employee's ticket."}` |
| `GET /tickets/{id}` | ticket exists, owned by caller | 200 | the ticket object |

## 5. Setup and execution commands

**Dependency file:** only `pyproject.toml` (PEP 621 `[project.dependencies]`
+ `[project.optional-dependencies].dev`). There is no `requirements.txt`
in this repo — that's intentional, not missing.

### Command to run only the Day 1 files (not the whole suite)

```bash
python -m pytest tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
```

This is the exact command to use once `tests/day2/` exists and you want
to isolate the baseline from new Day 2 files. Right now it collects the
same 7 tests as `python -m pytest -v`, because no Day 2 files exist yet.

### macOS / Linux

```bash
cd ai-qa-orchestration
source .venv/bin/activate
python -m pip show fastapi        # sanity check — confirms the right venv
python -m pytest -v
```

If `.venv` doesn't exist yet or `pip show fastapi` comes back empty:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows PowerShell

```powershell
cd ai-qa-orchestration
.venv\Scripts\Activate.ps1
python -m pip show fastapi
python -m pytest -v
```

If `.venv` doesn't exist yet or `pip show fastapi` comes back empty:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 6. Does Day 2 need a separate API terminal?

**No, not for the automated tests.** `tests/conftest.py` builds a
`fastapi.testclient.TestClient(app)`, which calls the ASGI app directly
in-process — confirmed by grepping the whole `tests/` and `app/`
trees for any real network call (`localhost`, `127.0.0.1`, `requests.`,
`httpx.Client`): there are none. `python -m pytest -v` is
self-contained.

A second terminal running the API is only needed if you want to demo it
manually with curl or `/docs` during the lesson — that's optional and
separate from testing. Same command on both platforms (from the README):

- macOS/Linux: `uvicorn app.main:app --reload --port 8000`
- Windows PowerShell: `uvicorn app.main:app --reload --port 8000`

The API then listens at `http://127.0.0.1:8000` (Swagger UI at
`/docs`).

## 7. Plain-English request flow

1. A test (or curl) sends `GET /tickets/TCK-1001` with header
   `X-Demo-Employee-ID: EMP001`.
2. FastAPI runs the `get_current_employee` dependency first: it reads
   the header, loads `employees.json`, and finds the Dana Whitfield
   record. If the header were missing or unrecognized, the request
   would stop here with a 400 and the route body would never run.
3. The route handler (`get_ticket` in `app/main.py`) loads
   `tickets.json` and calls `rules.find_ticket_by_id` to look for
   `TCK-1001`. If nothing matches, it stops with a 404.
4. If the ticket exists, `rules.employee_owns_ticket` compares the
   ticket's `employee_id` to the caller's. A mismatch stops here with
   403.
5. Only if all three checks pass does the route return the ticket JSON
   with a 200.

This is the flow every Day 2 test ultimately exercises, whether it's
checking the happy path, a 403, a 404, or a 400.

## 8. Baseline results (independently re-verified 2026-09-27)

```
$ source .venv/bin/activate
$ python -m pip show fastapi | head -5
Name: fastapi
Version: 0.141.1
$ python -m pytest tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
...
tests/test_tickets.py::test_get_own_ticket_returns_200 PASSED            [ 14%]
tests/test_tickets.py::test_get_other_employees_ticket_returns_403 PASSED [ 28%]
tests/test_tickets.py::test_ticket_matches_schema PASSED                 [ 42%]
tests/test_tickets.py::test_missing_ticket_returns_404 PASSED            [ 57%]
tests/test_employees.py::test_get_my_profile_returns_known_employee PASSED [ 71%]
tests/test_service_status.py::test_health_check_returns_ok PASSED        [ 85%]
tests/test_service_status.py::test_vpn_status_has_defined_status_and_update_time PASSED [100%]
======================== 7 passed, 1 warning in 0.06s =========================
```

- Python: 3.11.0 (satisfies `pyproject.toml`'s `>=3.11,<3.13`)
- pytest: 8.4.2
- fastapi (installed in this `.venv`): 0.141.1 — newer than the
  `>=0.110,<1.0` floor in `pyproject.toml`, still within range.
- The one warning is a harmless Starlette deprecation notice about
  `httpx`/`httpx2`, unrelated to test correctness.
- `test_missing_ticket_returns_404` (BR03) was added since the Day 1
  starter was first written — it is now part of the baseline, not a
  Day 2 exercise, so Day 2 material should not reintroduce it as new.

## 9. Unresolved issues / notes for the instructor

- **Extra pytest plugins in this machine's `.venv`:** `pytest-html`,
  `pytest-json-report`, and `pytest-metadata` are installed here but
  are **not** declared in `pyproject.toml`. A student's fresh
  `pip install -e ".[dev]"` will not get them (their pytest output
  will look slightly plainer — no "Plugins: json-report..." line) but
  will still pass the same 7 tests. Don't demo anything that depends on
  these plugins unless you add them to `pyproject.toml` first.
- **Minor style nit, not a defect:** `tests/test_tickets.py` is missing
  a blank line between `test_ticket_matches_schema` and
  `test_missing_ticket_returns_404` (PEP 8 wants two). Cosmetic only —
  left as-is rather than reformatting someone else's recent commit
  without being asked.
- **No blockers found.** All 7 existing tests pass from a clean
  `.venv` activation with no code changes required.

## 10. Proposed Day 2 test layout (not created yet)

A new `tests/day2/` folder, planned but intentionally not scaffolded
until the lesson itself. Pytest automatically shares fixtures from a
parent `conftest.py`, so every file below reuses the existing `client`
fixture from `tests/conftest.py` without redefining it.

| File | Purpose |
| --- | --- |
| `tests/day2/conftest.py` | Day-2-only fixtures layered on top of the existing `client` fixture — e.g. a small `auth_headers(employee_id)` helper that returns `{"X-Demo-Employee-ID": employee_id}`, so later files stop repeating that dict literal. |
| `tests/day2/test_01_fixtures.py` | Introduces fixtures as a concept: rewrite Day 1's `/employees/me` and `/services/vpn/status` checks using the new `auth_headers` fixture, so students see *why* a fixture is useful before anything more advanced. |
| `tests/day2/test_02_parameterized.py` | `@pytest.mark.parametrize` over the real ownership table in section 3 — one test function driving all 4 employee/own-ticket 200 cases (`EMP001`/`TCK-1001`, `EMP002`/`TCK-1002`, `EMP003`/`TCK-1003`, `EMP004`/`TCK-1004`) instead of four near-duplicate tests. |
| `tests/day2/test_03_ownership.py` | Extends BR01–BR03 systematically with parametrization: several mismatched employee/ticket pairs expecting 403, a missing-header case expecting 400, an unknown-employee-id case expecting 400, and the existing missing-ticket 404 case, but now table-driven instead of one-off. |
| `tests/day2/test_04_schema.py` | Builds on Day 1's single `test_ticket_matches_schema`: parametrize it across every ticket ID owned by the calling employee, and add one negative case asserting `jsonschema.validate` raises `ValidationError` against a deliberately malformed payload (e.g. a `status` value outside the enum). |

Day 1's tests in `tests/test_tickets.py`, `tests/test_employees.py`, and
`tests/test_service_status.py` are left untouched — Day 2 adds a
parallel folder rather than replacing the baseline.

**Status:** `tests/day2/conftest.py` and all four files above were
scaffolded in one earlier pass, before lessons were being taught one
topic at a time. Section 11 below is the first topic (fixtures) done
properly, lesson-by-lesson, with real verification. Files
`test_02_parameterized.py`, `test_03_ownership.py`, and
`test_04_schema.py` still exist on disk from that earlier pass and
still pass, but they have not yet been taught/verified as their own
lesson — treat them as provisional until each is revisited the same
way section 11 revisits fixtures.

## 11. Lesson 1 — Fixtures (implemented and verified 2026-09-27)

**File:** [`tests/day2/test_01_fixtures.py`](../tests/day2/test_01_fixtures.py)

**No new fixtures were needed.** [`tests/day2/conftest.py`](../tests/day2/conftest.py)
already had exactly what this lesson requires, so it was reused as-is:

```python
@pytest.fixture()
def auth_headers():
    def _auth_headers(employee_id: str) -> dict:
        return {"X-Demo-Employee-ID": employee_id}
    return _auth_headers
```

### Fixtures explained

| Fixture | Defined in | What it does |
| --- | --- | --- |
| `client` | `tests/conftest.py` | A `fastapi.testclient.TestClient` wired to the `app` object in `app/main.py`. Calls the ASGI app in-process — no network call, no running server. Available to every test file under `tests/` automatically (pytest shares a parent `conftest.py`'s fixtures downward). |
| `auth_headers` | `tests/day2/conftest.py` | A factory fixture. `auth_headers("EMP001")` returns `{"X-Demo-Employee-ID": "EMP001"}`, the exact header `get_current_employee()` in `app/main.py` requires. Exists so tests stop repeating the header dict literal. |

### The two tests

- `test_employee_a_retrieves_their_own_ticket` — Employee A = `EMP001`
  (Dana Whitfield) fetches `TCK-1001`.
- `test_employee_b_retrieves_their_own_ticket` — Employee B = `EMP002`
  (Marcus Lee) fetches `TCK-1002`.

Both identities and both ownership facts are copied from
`data/employees.json` / `data/tickets.json` (see section 3's table),
not derived from the response under test. Each test asserts three
independent things: `response.status_code == 200`, the returned
`ticket_id` matches what was requested, and the returned `employee_id`
matches the owner hardcoded from the data file — so a bug that made
the API return someone else's ticket with a 200 would still be caught.

### Files to open for this lesson

1. [`data/employees.json`](../data/employees.json) — the identities.
2. [`data/tickets.json`](../data/tickets.json) — ticket ownership (where
   the expected owners in the test come from).
3. [`app/main.py`](../app/main.py) — `get_current_employee` and
   `get_ticket`.
4. [`app/rules.py`](../app/rules.py) — `employee_owns_ticket`.
5. [`tests/conftest.py`](../tests/conftest.py) — the `client` fixture.
6. [`tests/day2/conftest.py`](../tests/day2/conftest.py) — the
   `auth_headers` fixture.
7. [`tests/day2/test_01_fixtures.py`](../tests/day2/test_01_fixtures.py)
   — the two tests themselves.

### Verified run (this run, this machine, 2026-09-27)

Command — the new file plus the three recorded Day 1 files, run
together:

```bash
python -m pytest tests/day2/test_01_fixtures.py tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
```

Result:

```
tests/day2/test_01_fixtures.py::test_employee_a_retrieves_their_own_ticket PASSED
tests/day2/test_01_fixtures.py::test_employee_b_retrieves_their_own_ticket PASSED
tests/test_tickets.py::test_get_own_ticket_returns_200 PASSED
tests/test_tickets.py::test_get_other_employees_ticket_returns_403 PASSED
tests/test_tickets.py::test_ticket_matches_schema PASSED
tests/test_tickets.py::test_missing_ticket_returns_404 PASSED
tests/test_employees.py::test_get_my_profile_returns_known_employee PASSED
tests/test_service_status.py::test_health_check_returns_ok PASSED
tests/test_service_status.py::test_vpn_status_has_defined_status_and_update_time PASSED
========================= 9 passed, 1 warning in 0.06s =========================
```

No blockers. The one warning is the same pre-existing Starlette/httpx
deprecation notice noted in section 8, unrelated to these tests.

## 12. Lesson 2 — Parametrization (implemented and verified 2026-09-27)

**File:** [`tests/day2/test_02_parameterized.py`](../tests/day2/test_02_parameterized.py)
(rewritten from the earlier provisional version referenced in section
10 — the earlier version only covered four 200 cases; this version
replaces it with the five-scenario spec below).

### Syntax explained (beginner language)

`@pytest.mark.parametrize("employee_id, ticket_id, expected_status", CASES)`
tells pytest to run the test function once for every entry in `CASES`,
unpacking that entry's values into the three named arguments. Each
entry is built with `pytest.param(value1, value2, value3, id="...")` —
the `id` is what makes `pytest -v` print a readable label like
`test_ticket_access_scenarios[employee_a_requests_employee_bs_ticket]`
instead of pytest's default auto-generated id.

### The 5 cases

| Case id | Employee | Ticket requested | Expected status |
| --- | --- | --- | --- |
| `employee_a_requests_own_ticket` | EMP001 | TCK-1001 | 200 |
| `employee_b_requests_own_ticket` | EMP002 | TCK-1002 | 200 |
| `employee_a_requests_employee_bs_ticket` | EMP001 | TCK-1002 | 403 |
| `employee_b_requests_employee_as_ticket` | EMP002 | TCK-1001 | 403 |
| `valid_employee_requests_well_formed_missing_ticket` | EMP001 | TCK-9999 | 404 |

Assertions per outcome (no case accepts an alternative status code —
each is an exact `==` check, not a set membership check):

- **200:** `ticket_id` and `employee_id` in the body match the request.
- **403:** body equals exactly `{"detail": "You may not view another employee's ticket."}` — checked with a full dict equality, plus explicit `assert "subject"/"description"/"status" not in body`, so a regression that leaked the foreign ticket's content alongside the error would be caught, not just a wrong status code.
- **404:** body equals exactly `{"detail": "Ticket not found: TCK-9999"}`.

### Overlap accounting — do not double-count

- `employee_a_requests_own_ticket` and `employee_b_requests_own_ticket`
  are the **same employee/ticket pairs** as
  `tests/day2/test_01_fixtures.py`'s two tests. They're intentionally
  repeated here to demonstrate parametrization mechanics on a case the
  student already trusts, not to add new coverage. Count each of those
  two scenarios once (against test_01), not twice.
- The 403 pair here (`EMP001`→`TCK-1002`, `EMP002`→`TCK-1001`) and the
  404 case (`EMP001`→`TCK-9999`) also happen to match individual cases
  already present in the provisional `tests/day2/test_03_ownership.py`
  from the earlier scaffolding pass (see section 10's status note).
  That file has not been taught/verified as its own lesson yet, so
  treat this file's 403/404 cases as the first *verified* appearance of
  that coverage; `test_03_ownership.py` will need its own overlap
  review when its lesson comes up, rather than being counted as 3
  additional new cases on top of these.
- **Net new, verified, non-overlapping coverage from this file:** 3
  scenarios (the two 403 directions and the 404 case). 2 of the 5
  parametrized cases are deliberate repeats for teaching purposes.

### Verified run (this run, this machine, 2026-09-27)

```bash
python -m pytest tests/day2/test_01_fixtures.py tests/day2/test_02_parameterized.py tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
```

```
tests/day2/test_01_fixtures.py::test_employee_a_retrieves_their_own_ticket PASSED
tests/day2/test_01_fixtures.py::test_employee_b_retrieves_their_own_ticket PASSED
tests/day2/test_02_parameterized.py::test_ticket_access_scenarios[employee_a_requests_own_ticket] PASSED
tests/day2/test_02_parameterized.py::test_ticket_access_scenarios[employee_b_requests_own_ticket] PASSED
tests/day2/test_02_parameterized.py::test_ticket_access_scenarios[employee_a_requests_employee_bs_ticket] PASSED
tests/day2/test_02_parameterized.py::test_ticket_access_scenarios[employee_b_requests_employee_as_ticket] PASSED
tests/day2/test_02_parameterized.py::test_ticket_access_scenarios[valid_employee_requests_well_formed_missing_ticket] PASSED
tests/test_tickets.py::test_get_own_ticket_returns_200 PASSED
tests/test_tickets.py::test_get_other_employees_ticket_returns_403 PASSED
tests/test_tickets.py::test_ticket_matches_schema PASSED
tests/test_tickets.py::test_missing_ticket_returns_404 PASSED
tests/test_employees.py::test_get_my_profile_returns_known_employee PASSED
tests/test_service_status.py::test_health_check_returns_ok PASSED
tests/test_service_status.py::test_vpn_status_has_defined_status_and_update_time PASSED
========================= 14 passed, 1 warning in 0.07s =========================
```

No blockers. Same pre-existing Starlette/httpx deprecation warning as
before.

## 13. Lesson 3 — Ownership, BR02, with fault injection (implemented and verified 2026-09-27)

**File:** [`tests/day2/test_03_ownership.py`](../tests/day2/test_03_ownership.py)
(fully rewritten from the earlier provisional version referenced in
section 10 — that version mixed BR01/BR02/BR03 into one parametrized
test; this version is scoped to BR02 only, two concrete directions,
plus the fault-injection drill below).

**Also changed:** [`tests/conftest.py`](../tests/conftest.py) gained one
new `pytest_addoption` hook registering `--day2-fault`. This is the
only change to a Day 1 shared file made for this lesson — see "Why
tests/conftest.py had to change" below for why it couldn't live in
tests/day2/conftest.py instead. No Day 1 test file was touched, and the
option defaults to `None` (off), so Day 1 behavior is provably
unchanged (verified below).

### Enforcement location, in beginner language

The rule "you can only see your own ticket" (BR02) lives in exactly one
function, `employee_owns_ticket` in `app/rules.py`. It's called exactly
once, inside `get_ticket` in `app/main.py`, right after the ticket is
looked up and right before it's returned:

```python
if not rules.employee_owns_ticket(ticket, employee["employee_id"]):
    raise HTTPException(status_code=403, detail="...")
```

If that one check is ever skipped, deleted, or always says "yes" — the
`if not ...` branch never runs, the 403 is never raised, and
`get_ticket` falls through to `return ticket`, handing back a 200 with
the real ticket's full contents to whoever asked, regardless of who
owns it.

### The two tests

- `test_employee_a_cannot_view_employee_bs_ticket` — EMP001 requests
  `TCK-1002` (owned by EMP002).
- `test_employee_b_cannot_view_employee_as_ticket` — EMP002 requests
  `TCK-1001` (owned by EMP001).

Both directions are checked as separate tests because the code above
only ever compares "the ticket in front of it" to "the caller's own
id" — it has no wider two-way concept — so a bug could break one
direction without breaking the other. Each test asserts the exact
denial body `{"detail": "You may not view another employee's ticket."}`
and explicitly asserts `"subject"`, `"description"`, and `"status"` are
absent from it, so a regression that leaked the real ticket's content
alongside (or instead of) the correct status code would still be
caught.

### Fault injection: `--day2-fault=ownership`

**What it does:** monkeypatches `app.rules.employee_owns_ticket` to
always return `True` — simulating the BR02 check above being deleted —
for the exact duration of each test in this file only.

**What breaks, in beginner language:** with the patch active,
`get_ticket` still executes the `if not rules.employee_owns_ticket(...)`
line, but that call now always reports "yes, this is your ticket," so
the `raise HTTPException(403, ...)` branch is unreachable. Every ticket
request succeeds with a 200 and the real ticket body, no matter who is
asking. The two tests' assertions are never changed for this run —
they still assert `response.status_code == 403` — so under the fault
they fail with `assert 200 == 403`, a concrete, readable proof that
these tests would catch this exact regression.

**Why this counts as "isolated," not a persistent unsafe toggle:**

- It never touches `app/rules.py` on disk.
- It never runs unless `--day2-fault=ownership` is explicitly passed.
- It never changes `data/tickets.json` or `data/employees.json`.
- It never touches BR01 (the header/identity check) — only the
  ownership comparison.
- pytest's built-in `monkeypatch` fixture is function-scoped, so the
  patch is automatically reverted the instant each test function
  returns (pass, fail, or error) — no manual cleanup code was written.
- It cannot reach a real running instance of the API (e.g.
  `uvicorn app.main:app`), because that process never imports pytest or
  this file at all.
- The fixture that applies the patch (`_maybe_break_ownership_enforcement`)
  is defined inside `test_03_ownership.py` itself, not in a shared
  conftest, so it is autoused only for tests in this one file.

**Not marked xfail, on purpose:** when the fault is active, the two
tests are meant to genuinely FAIL, in plain red, not be reported as an
expected failure. That failure *is* the deliverable — proof the tests
detect a broken check — and `xfail` would hide exactly that signal.

### Why `tests/conftest.py` had to change (not `tests/day2/conftest.py`)

`pytest_addoption` only registers a flag reliably if it's defined in a
conftest.py that pytest scans while resolving which paths to collect —
and a bare `python -m pytest -v` run from the project root (which is
how section 5's setup instructions tell a student to run everything,
relying on `testpaths = ["tests"]` in `pyproject.toml`) never gives
pytest a reason to look inside `tests/day2/` at that early point. A
`pytest_addoption` placed in `tests/day2/conftest.py` would work when
invoking `pytest tests/day2/...` directly, but would make the *entire*
suite crash with "unrecognized arguments: --day2-fault" the moment
someone tried `python -m pytest --day2-fault=ownership -v` from the
root without naming a day2 path. Registering it in the shared
`tests/conftest.py` avoids that trap. The option still does nothing on
its own — only this one file's local fixture reads it.

### Verified (this run, this machine, 2026-09-27)

**1. Normal run — passes:**

```bash
python -m pytest tests/day2/test_03_ownership.py -v
```
```
tests/day2/test_03_ownership.py::test_employee_a_cannot_view_employee_bs_ticket PASSED
tests/day2/test_03_ownership.py::test_employee_b_cannot_view_employee_as_ticket PASSED
========================= 2 passed, 1 warning in 0.02s =========================
```

**2. With the fault — genuinely fails (not xfail):**

```bash
python -m pytest tests/day2/test_03_ownership.py --day2-fault=ownership -v
```
```
tests/day2/test_03_ownership.py::test_employee_a_cannot_view_employee_bs_ticket FAILED
tests/day2/test_03_ownership.py::test_employee_b_cannot_view_employee_as_ticket FAILED
E       assert response.status_code == 403
E       assert 200 == 403
=================== 2 failed, 1 warning in 0.04s ====================
```

**3. Normal run again — passes, fault did not persist:**

```bash
python -m pytest tests/day2/test_03_ownership.py -v
```
```
tests/day2/test_03_ownership.py::test_employee_a_cannot_view_employee_bs_ticket PASSED
tests/day2/test_03_ownership.py::test_employee_b_cannot_view_employee_as_ticket PASSED
========================= 2 passed, 1 warning in 0.01s =========================
```

**Bonus isolation check — full suite with the fault flag:** ran
`python -m pytest --day2-fault=ownership -v` across all 23 collected
Day 1 + Day 2 tests. Result: **exactly the same 2 tests failed**
(`test_03_ownership.py`'s two tests); all 21 others — including Day
1's own `test_get_other_employees_ticket_returns_403` and
`test_02_parameterized.py`'s two 403 cases — still passed. This
confirms the fault does not leak into any other file even within the
same process, because pytest runs tests one at a time and
`monkeypatch` reverts between each one.

**Bonus regression check — full suite with no flag, and Day 1 files
alone:** `python -m pytest -v` → 23 passed. `python -m pytest
tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v`
→ 7 passed. Confirms the `tests/conftest.py` addition changed nothing
about Day 1's recorded behavior.

No blockers.

## 14. Lesson 4 — Reusable JSON Schema validation (implemented and verified 2026-09-27)

**File:** [`tests/day2/test_04_schema.py`](../tests/day2/test_04_schema.py)
(fully rewritten — the earlier provisional version parametrized one
schema across all 6 tickets plus a hand-built negative case; this
version covers 4 distinct real response categories instead, per this
lesson's spec).

**Also changed:**

- [`tests/day2/conftest.py`](../tests/day2/conftest.py) — added the
  `validate_against_schema` fixture (reusable JSON Schema validation
  against this project's own contract files in `schemas/`).
- [`tests/conftest.py`](../tests/conftest.py) — extended `--day2-fault`'s
  `choices` from `["ownership"]` to
  `["ownership", "missing-status", "wrong-status-type"]`. Still
  registered at the top level for the same reason given in section 13;
  still does nothing unless explicitly passed.
- `schemas/employee.schema.json`, `schemas/service_status.schema.json`,
  `schemas/error.schema.json` — three new schema files, alongside the
  existing `schemas/ticket.schema.json`.
- `pyproject.toml` — **no change.** `jsonschema>=4.21,<5.0` was already
  a declared dependency (line 14) before this lesson; verified with
  `grep -n jsonschema pyproject.toml` rather than adding a redundant
  duplicate entry.

### Reusable validation

`validate_against_schema(instance, schema_filename)` (in
`tests/day2/conftest.py`) loads a schema file from `schemas/` and runs
`jsonschema.validate`. Every test in this file calls it the same way,
so the "how do I check a response against a schema" logic is written
once, not once per test.

### JSON Schema keywords, explained for beginners

| Keyword | Meaning |
| --- | --- |
| `"type": "object"` | The value must be a JSON object (a dict), not a list/string/number. |
| `"properties"` | A map from field name to that field's own schema. Describes a field's shape *if present* — does not, by itself, make it mandatory. |
| `"required"` | The list of field names that MUST be present. This is what makes a field mandatory. |
| `"type": "string"` (inside a property) | That specific field's value must be text. This is what catches `wrong-status-type`: the key is present (`required` is satisfied) but the value is the wrong kind. |

### The 4 real API response categories

| # | Category | Request | Expected status | Schema |
| --- | --- | --- | --- | --- |
| 1 | Employee profile | `GET /employees/me` (EMP001) | 200 | `employee.schema.json` |
| 2 | Ticket | `GET /tickets/TCK-1001` (EMP001) | 200 | `ticket.schema.json` |
| 3 | Service status | `GET /services/vpn/status` | 200 | `service_status.schema.json` |
| 4 | Error response | `GET /tickets/TCK-9999` (EMP001) | 404 | `error.schema.json` |

Every test asserts the expected status code first and only then
validates the body — checking an error body against a success schema
(or vice versa) would test the wrong contract.

A fifth test, `test_beginner_schema_example_missing_required_field`,
validates a hand-built dict (not a real response) purely to show what
`required` does in isolation. **It is explicitly not counted among the
4 API response categories above** — 4 is the real, API-backed count.

### Fault injection: `--day2-fault=missing-status` / `wrong-status-type`

Both target BR04 (`GET /services/vpn/status`'s `"status"` field) by
monkeypatching `app.data.load_service_status` — the function
`get_vpn_status` in `app/main.py` calls to build its response — inside
a file-scoped `autouse` fixture in `test_04_schema.py`. The fault is
injected in the app's own response-generation path (the data-loading
step the route depends on), not by mutating `response.json()` inside a
test after the call. `get_vpn_status` itself is never touched or aware
anything changed, and `data/service_status.json` on disk is read fresh
and copied in memory each time — never written to.

- `missing-status`: returns a copy of the real status payload with the
  `"status"` key deleted.
- `wrong-status-type`: returns a copy of the real payload with
  `"status"` replaced by the integer `1` instead of a string.

**Did FastAPI's own response handling catch either fault first?**
Checked directly rather than assumed: **no.** Neither route in this app
declares `response_model=` — both use only a bare `-> dict` return-type
hint, which FastAPI does not treat as a validation contract; it only
serializes whatever the function returns. Both fault payloads are
ordinary JSON-serializable values (a dict short one key; an int where a
string was expected), so in both runs the server returned a plain `200
OK` with the malformed body — no framework-level rejection at any
point. `jsonschema`, invoked explicitly by this test file, was the only
layer that caught either fault. This is a real, verified result (see
raw output below), not the assumed/expected outcome — if this app ever
adds `response_model=` to `get_vpn_status`, this section would need
re-verification, since Pydantic could then start rejecting these same
payloads before the response is even sent.

### Verified (this run, this machine, 2026-09-27)

**1. Baseline — 5 passed:**

```bash
python -m pytest tests/day2/test_04_schema.py -v
```
```
test_employee_profile_matches_schema PASSED
test_ticket_matches_schema PASSED
test_service_status_matches_schema PASSED
test_missing_ticket_error_matches_schema PASSED
test_beginner_schema_example_missing_required_field PASSED
========================= 5 passed, 1 warning in 0.02s =========================
```

**2a. `--day2-fault=missing-status` — detected:**

```bash
python -m pytest tests/day2/test_04_schema.py --day2-fault=missing-status -v
```
```
test_service_status_matches_schema FAILED
E   jsonschema.exceptions.ValidationError: 'status' is a required property
On instance:
    {'service': 'vpn', 'updated_at': '2026-09-25T08:00:00Z', 'message': 'VPN service is running normally.'}
==================== 1 failed, 4 passed, 1 warning in 0.04s ====================
```
Response was a real `200 OK` — confirms no framework-level rejection;
`jsonschema` caught it.

**2b. `--day2-fault=wrong-status-type` — detected:**

```bash
python -m pytest tests/day2/test_04_schema.py --day2-fault=wrong-status-type -v
```
```
test_service_status_matches_schema FAILED
E   jsonschema.exceptions.ValidationError: 1 is not of type 'string'
On instance['status']:
    1
==================== 1 failed, 4 passed, 1 warning in 0.04s ====================
```
Again a real `200 OK`; again `jsonschema`, not FastAPI, caught it.

**3. Baseline again — 5 passed, fault did not persist:**

```bash
python -m pytest tests/day2/test_04_schema.py -v
```
```
========================= 5 passed, 1 warning in 0.02s =========================
```

**Bonus isolation check — full 23-test suite with each fault flag:**
`python -m pytest --day2-fault=missing-status -v` and `python -m pytest
--day2-fault=wrong-status-type -v` each produced **exactly** `1 failed,
20 passed` — only `test_service_status_matches_schema` failed each
time. Every other test, including Day 1's own
`test_vpn_status_has_defined_status_and_update_time` (which also reads
the `"status"` field, in a different file), stayed unaffected —
confirming the fixture's file-scoping works even for a test that reads
the same field this fault targets.

**Bonus regression check:** `python -m pytest -v` (no flag) → 21
passed (23 minus the 2 fewer items in the rewritten `test_04_schema.py`
compared to its earlier provisional version). `python -m pytest
tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v`
→ 7 passed, unchanged.

No blockers.
