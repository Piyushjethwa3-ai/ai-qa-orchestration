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

A second terminal running `uvicorn app.main:app --reload --port 8000`
is only needed if you want to demo the API manually with curl or
`/docs` during the lesson — that's optional and separate from testing.

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

## 8. Baseline results (this run, this machine)

```
$ source .venv/bin/activate
$ python -m pytest -v
...
tests/test_employees.py::test_get_my_profile_returns_known_employee PASSED
tests/test_service_status.py::test_health_check_returns_ok PASSED
tests/test_service_status.py::test_vpn_status_has_defined_status_and_update_time PASSED
tests/test_tickets.py::test_get_own_ticket_returns_200 PASSED
tests/test_tickets.py::test_get_other_employees_ticket_returns_403 PASSED
tests/test_tickets.py::test_ticket_matches_schema PASSED
tests/test_tickets.py::test_missing_ticket_returns_404 PASSED
======================== 7 passed, 1 warning in 0.05s =========================
```

- Python: 3.11.0 (satisfies `pyproject.toml`'s `>=3.11,<3.13`)
- pytest: 8.4.2
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

None of these files exist yet, and Day 1's four passing tests in
`tests/test_tickets.py`, `tests/test_employees.py`, and
`tests/test_service_status.py` are left untouched — Day 2 adds a
parallel folder rather than replacing the baseline.
