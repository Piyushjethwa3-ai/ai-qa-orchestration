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
| `tests/` | Baseline pytest suite (`TestClient`, no network calls) |
| `docs/business_rules.md` | BR01–BR04, in plain language |
| `docs/week1-learning-log.md` | Template for your own daily notes |
| `docs/instructor-challenge.md` | Instructor-only defect-injection exercise |

## Prerequisites

- Python 3.11 (the project pins `>=3.11,<3.13`)
- No API keys or accounts needed — everything here is local and synthetic

## Setup — macOS / Linux (bash/zsh)

```bash
# From the project root
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

## Setup — Windows (PowerShell)

```powershell
# From the project root
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[dev]"
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

With the virtual environment active (same command on macOS/Linux and
Windows PowerShell):

```bash
pytest -v
```

This runs the baseline suite in `tests/`: one test per endpoint plus a
dedicated ticket-ownership test. It is intentionally small — Day 1 and
Day 2 exercises ask you to extend it (missing header, unknown employee,
missing ticket, and more).

## Business rules

See [`docs/business_rules.md`](docs/business_rules.md) for BR01–BR04 and
where each one is implemented in the code.
