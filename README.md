# Northstar Services — IT Service Desk API (Week 1 Starter)

A small, deterministic FastAPI service for Week 1 of the AI Quality
Engineering and QA Orchestration program. Northstar Services is a
fictional company; employees ask its IT service desk for VPN help.

This starter has **no LLM, no RAG, no chat UI, no database, no Docker,
and no CI workflow**. It reads plain JSON files and applies simple,
predictable business rules — the goal is a codebase a learner new to
Python test automation can read end to end and reason about with
confidence, before AI features are layered on in later weeks.

## What's in here

| Path | What it is |
| --- | --- |
| `app/main.py` | FastAPI routes (HTTP layer only) |
| `app/data.py` | Functions that read the JSON files in `data/` |
| `app/rules.py` | Business-rule functions (ownership checks, lookups) |
| `data/employees.json` | 4 synthetic employees |
| `data/tickets.json` | 6 synthetic VPN tickets |
| `data/service_status.json` | Current synthetic VPN status |
| `schemas/ticket.schema.json` | JSON Schema a ticket must satisfy |
| `schemas/employee.schema.json` | JSON Schema for an employee profile response |
| `schemas/service_status.schema.json` | JSON Schema for the VPN status response (BR04) |
| `schemas/error.schema.json` | JSON Schema for the API's error shape (`{"detail": ...}`) |
| `tests/conftest.py` | Shared `client` fixture + the `--day2-fault` option registration |
| `tests/test_*.py` | Day 1 baseline suite (`TestClient`, no network calls) |
| `tests/day2/` | Day 2 lessons: fixtures, parametrization, ownership, schema validation |
| `docs/business_rules.md` | BR01–BR04, in plain language |
| `docs/week1-learning-log.md` | Template for your own daily notes |
| `docs/day2-instructor-map.md` | Day 2 lesson-by-lesson map and verification record |
| `docs/day2-run-evidence.md` | Sanitised Day 2 run results and coverage summary |

## Prerequisites

- Python 3.11 (the project pins `>=3.11,<3.13`)
- No API keys or accounts needed — everything here is local and synthetic

## ⚠️ Activate the virtual environment in every new terminal

This project keeps its dependencies in a local virtual environment at
`.venv/`. **Every dependency (FastAPI, pytest, etc.) is installed only
inside `.venv/`, never globally.** Each time you open a *new* terminal
(including a new VS Code integrated terminal tab), you must activate it
again before running any project command:

- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.venv\Scripts\Activate.ps1`

Your prompt should then show a `(.venv)` prefix. If you skip this step,
commands like `pytest` may silently run a *different*, unrelated Python
installation on your machine that does not have this project's packages
— see [Troubleshooting](#troubleshooting) below if that happens.

Also prefer `python -m pytest -v` over a bare `pytest -v`. Running
pytest as a module of the currently active `python` is more reliable
than relying on a `pytest` command found elsewhere on your system PATH.

## Setup — macOS / Linux (bash/zsh)

```bash
# From the project root
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Setup — Windows (PowerShell)

```powershell
# From the project root
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks the activation script, run PowerShell as your normal
user and execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

then re-run the activation command above.

## Running the API locally

macOS/Linux:

```bash
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell:

```powershell
uvicorn app.main:app --reload --port 8000
```

The API is now at `http://127.0.0.1:8000`. Interactive docs (Swagger UI)
are at `http://127.0.0.1:8000/docs`.

## Calling the endpoints with curl

All employee- and ticket-scoped endpoints require the demo header
`X-Demo-Employee-ID`. Valid demo IDs are `EMP001`, `EMP002`, `EMP003`,
`EMP004` (see `data/employees.json`).

These curl commands work the same way on macOS/Linux and in Windows
PowerShell (Windows 10+ ships `curl.exe`).

**Health check:**

```bash
curl http://127.0.0.1:8000/health
```

**Your employee profile:**

```bash
curl -H "X-Demo-Employee-ID: EMP001" http://127.0.0.1:8000/employees/me
```

**VPN service status:**

```bash
curl http://127.0.0.1:8000/services/vpn/status
```

**Get your own ticket (expect 200):**

```bash
curl -i -H "X-Demo-Employee-ID: EMP001" http://127.0.0.1:8000/tickets/TCK-1001
```

**Try to get someone else's ticket (expect 403):**

```bash
curl -i -H "X-Demo-Employee-ID: EMP002" http://127.0.0.1:8000/tickets/TCK-1001
```

**Request a ticket that doesn't exist (expect 404):**

```bash
curl -i -H "X-Demo-Employee-ID: EMP001" http://127.0.0.1:8000/tickets/TCK-9999
```

**Omit the demo header (expect 400):**

```bash
curl -i http://127.0.0.1:8000/employees/me
```

## Running the tests

**Every test command in this section is identical on macOS/Linux and
Windows PowerShell.** Only the activation step differs, and you must do
it first, in every new terminal:

| Platform | Activate | Install/refresh dependencies |
| --- | --- | --- |
| macOS/Linux | `source .venv/bin/activate` | `python -m pip install -e ".[dev]"` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` | `python -m pip install -e ".[dev]"` |

`".[dev]"` installs pytest plus the two report plugins (`pytest-html`,
`pytest-json-report`) used in the report section below. If you set this
project up before Day 2, re-run the install command to pick them up.

### Do I need the API running in another terminal?

**No — not for any test command below.** The tests use FastAPI's
`TestClient`, which calls the app in-process; there is no network call
and no server to start. You only need `uvicorn` if you want to poke the
API by hand with curl or Swagger UI (see
[Running the API locally](#running-the-api-locally) above):

```bash
uvicorn app.main:app --reload --port 8000
```

That command is the same on macOS/Linux and Windows PowerShell.

### Day 1 tests only

The three original Day 1 files, named explicitly:

```bash
python -m pytest tests/test_tickets.py tests/test_employees.py tests/test_service_status.py -v
```

Expected: **7 passed**.

### Day 2 tests only

```bash
python -m pytest tests/day2 -v
```

Expected: **14 passed** — fixtures (2), parametrization (5), ownership
(2), and schema validation (5).

### Full suite

```bash
python -m pytest -v
```

Expected: **21 passed** (7 Day 1 + 14 Day 2).

### Fault demonstrations (expected failures)

Day 2 includes a test-only fault-injection flag, `--day2-fault`, used to
prove the tests actually detect broken behaviour rather than passing
vacuously. **It is off by default and has no effect on the application
itself** — it only works inside pytest, only when passed explicitly, and
pytest's `monkeypatch` reverts it after every single test. It never
writes to `data/`.

Each command below is *supposed* to fail. A failure here is the correct,
expected result:

| Command | Expected result |
| --- | --- |
| `python -m pytest tests/day2/test_03_ownership.py --day2-fault=ownership -v` | **2 failed** — both cross-employee tests fail with `assert 200 == 403`, because the BR02 ownership check was patched to always pass. |
| `python -m pytest tests/day2/test_04_schema.py --day2-fault=missing-status -v` | **1 failed, 4 passed** — `test_service_status_matches_schema` fails with `ValidationError: 'status' is a required property`. |
| `python -m pytest tests/day2/test_04_schema.py --day2-fault=wrong-status-type -v` | **1 failed, 4 passed** — same test fails with `ValidationError: 1 is not of type 'string'`. |

To confirm nothing persisted, re-run the same file with no flag — it
should go back to all-passing:

```bash
python -m pytest tests/day2 -v
```

### Report generation

Both report plugins come from `".[dev]"`. Output goes to `reports/`,
which is **git-ignored on purpose** — reports embed local machine paths
and are rebuilt on demand, so they are not committed.

```bash
python -m pytest -v --html=reports/day2-report.html --self-contained-html --json-report --json-report-file=reports/day2-report.json
```

Same command on macOS/Linux and Windows PowerShell. If `reports/`
doesn't exist yet:

- macOS/Linux: `mkdir -p reports`
- Windows PowerShell: `New-Item -ItemType Directory -Force reports`

Open `reports/day2-report.html` in a browser for the human-readable
version; `reports/day2-report.json` is the machine-readable one.

Sanitised, committed evidence of the Day 2 runs lives in
[`docs/day2-run-evidence.md`](docs/day2-run-evidence.md) instead of the
raw reports.

## Business rules

See [`docs/business_rules.md`](docs/business_rules.md) for BR01–BR04 and
where each one is implemented in the code.

## Troubleshooting

### "ModuleNotFoundError: No module named 'fastapi'" when running pytest

This means the terminal is not using this project's `.venv`. It is
almost always because a *new* terminal was opened and `.venv` was never
activated in it, so `pytest` (or `python`) fell back to some other
Python installation on your machine that doesn't have this project's
packages installed.

**macOS/Linux — run these one at a time and read the output of each:**

```bash
source .venv/bin/activate
python -m pip show fastapi
python -m pytest -v
```

- `source .venv/bin/activate` must succeed silently and your prompt
  should now start with `(.venv)`.
- `python -m pip show fastapi` should print a `Name: fastapi` block. If
  it instead prints `WARNING: Package(s) not found: fastapi`, the
  environment you activated is not the one the project was installed
  into (or the install step was never run in it).
- If FastAPI is missing inside the activated `.venv`, install the
  project's dependencies into it:

  ```bash
  python -m pip install -e ".[dev]"
  ```

  Then re-run `python -m pytest -v`.

**Windows PowerShell — the same steps:**

```powershell
.venv\Scripts\Activate.ps1
python -m pip show fastapi
python -m pytest -v
```

If FastAPI is missing:

```powershell
python -m pip install -e ".[dev]"
```

### A second, unrelated virtual environment folder

If you (or an editor) ever created a second environment folder, such as
a plain `venv/` alongside `.venv/`, make sure you always activate
`.venv/` specifically. Two environments with similar names is a common
source of this exact error — when in doubt, run `python -m pip show
fastapi` after activating to confirm you're in the right one.
