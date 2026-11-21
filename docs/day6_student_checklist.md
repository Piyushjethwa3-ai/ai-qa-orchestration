# Day 6 student handoff checklist

> Synthetic training material. The company, people and policies are fictional. **Nothing in this repository calls an LLM, the network or any API, needs an API key, or changes a real account or password.** Every command is deterministic: the same command prints the same text every time.

**Repository:** https://github.com/Piyushjethwa3-ai/ai-qa-orchestration.git  (branch `main`)

Work through this top to bottom. Tick each box only when you saw the **expected result**. If you did not, go to the troubleshooting section at the end before moving on.

## 1. Set-up on a fresh clone

### macOS / Linux (Terminal)

- [ ] **Python 3.11 is installed.** `python3.11 --version` → `Python 3.11.x`
- [ ] **Clone and enter the project.**
  ```bash
  git clone https://github.com/Piyushjethwa3-ai/ai-qa-orchestration.git
  cd ai-qa-orchestration
  ```
- [ ] **Create and activate the virtual environment.** Your prompt now starts with `(.venv)`.
  ```bash
  python3.11 -m venv .venv
  source .venv/bin/activate
  ```
- [ ] **Install.** It finishes without an error. No API key and no extra download are needed.
  ```bash
  python -m pip install --upgrade pip
  python -m pip install -e ".[dev]"
  ```

### Windows (PowerShell)

- [ ] **Python 3.11 is installed.** `py -3.11 --version` → `Python 3.11.x`
- [ ] **Clone and enter the project.**
  ```powershell
  git clone https://github.com/Piyushjethwa3-ai/ai-qa-orchestration.git
  cd ai-qa-orchestration
  ```
- [ ] **Create and activate the virtual environment.** Your prompt now starts with `(.venv)`.
  ```powershell
  py -3.11 -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
  If PowerShell refuses to run the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and activate again.
- [ ] **Install.** It finishes without an error.
  ```powershell
  python -m pip install --upgrade pip
  python -m pip install -e ".[dev]"
  ```

## 2. Check that everything works (identical on macOS/Linux and Windows)

- [ ] **Run every test.** Expected: `856 passed`, meaning 856 tests passed, 0 failed, 0 skipped. A fresh installation may display one third-party Starlette/httpx deprecation warning. This does not indicate a test failure. It takes under a minute.
  ```
  python -m pytest -q
  ```
- [ ] **Run the trajectory evaluation.** Expected: `passed 36 of 36`, and the exit code is 0 (macOS/Linux: `echo $?`; PowerShell: `$LASTEXITCODE`).
  ```
  python -m evaluators trajectories
  ```
  It saves a report under `reports/agent/`. That folder is git-ignored, so it never goes into a commit.

## 3. The five demonstrations

Run each command and find the **line to look for**. The full guide, with all expected output and what to observe, is
[`docs/day6_demo_guide.md`](day6_demo_guide.md). The commands are the same on every platform.

- [ ] **Demo 1: a successful VPN fix and ticket (BR03, BR04, BR06, BR08).**
  ```
  python -m app.governance demo vpn-ticket
  ```
  Look for: `PENDING_CONFIRMATION` first ("Nothing has been created yet"), then `TICKET_CREATED` with `TCK-1007`.
- [ ] **Demo 2: another employee's ticket is refused (BR01, BR02).**
  ```
  python -m app.governance demo cross-user
  ```
  Look for: `TICKET_UNAVAILABLE` and `DENIED: not your ticket`, then `SUCCESS: TCK-1001` for the real owner.
- [ ] **Demo 3: no ticket without confirmation (BR06).**
  ```
  python -m app.governance demo no-confirmation
  ```
  Look for: `DENIED: employee confirmation is required`, `DENIED: confirmation required (unknown_confirmation)`, then `SUCCESS: TCK-1007`.
- [ ] **Demo 4: a privileged action needs IT approval (BR06, BR07, BR11, BR12).**
  ```
  python -m app.governance demo privileged
  ```
  Look for: `DENIED: approval not valid (pending)`, `DENIED: not_an_approver`, `APPROVED by APR001`, `PRIVILEGED_EXECUTED`, `DENIED: approval not valid (already_used)` and `hash chain intact: True`.
- [ ] **Demo 5: prompt injection through a document (BR12).**
  ```
  python -m evaluators injection-demo
  ```
  Look for: six requested actions, all refused; `approval PRV-0001 status : PENDING`, `privileged executions    : 0`, `protected data leaked    : no`.
- [ ] **(Optional) Try it yourself.** `python -m app.agent chat --employee EMP002` or `python -m app.governance chat --employee EMP001`. Type `/help`.

## 4. What you should be able to explain afterwards

- [ ] Why the Week 5 agent is **not** an LLM, and what that does and does not let these tests prove.
- [ ] Where a restricted action is blocked **if the model asks for it anyway** (the gateway and the tools, not the prompt).
- [ ] The difference between the employee's **confirmation**, the IT **approval** and a **release** approval.
- [ ] Why the approval is bound to the employee, the action, the exact parameters and the request ID, and is single use.
- [ ] Why the refusal for someone else's request looks identical to a request that does not exist.
- [ ] One failure the tests found, what caused it, what changed and how it was verified (examples are in `docs/day6_notes.md`, section 4).

## 5. Rules for working in this repository

- Do **not** change an expected result or a label to make a test or demo pass. If an output changes, a test fails and names the document that is out of date.
- Do **not** add API keys, passwords or tokens to any file. None are needed.
- The tickets the agent creates live in **memory only**. `GET /tickets/TCK-1007` in the Week 1 API returns 404 for a ticket the agent just created. That is expected.
- `reports/` is git-ignored on purpose. Do not commit generated reports.

## 6. Troubleshooting

| You see | Likely cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'fastapi'` (or `pytest`) | The virtual environment is not active in this terminal | Activate it again (step 1), then `python -m pip install -e ".[dev]"` |
| `No module named evaluators` | The editable install is older than this version | Run `python -m pip install -e ".[dev]"` again |
| PowerShell: "running scripts is disabled" | Execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again |
| `python3.11: command not found` | Python 3.11 is not installed | Install Python 3.11 (this project needs 3.11 or 3.12) |
| A different test count from the one above | Your copy has changed, or an old checkout | `git status`, then `git pull`; the count above is for the released version |
| `Address already in use` when starting the optional API server | Port 8000 is taken | Add `--port 8001` to the `uvicorn` command |

## 7. Limits to be honest about

The agent is rule-based Python, not a language model, so nothing here shows how a real model behaves. The injection demonstration uses a deliberately gullible stand-in. Identity is a training header, not real authentication. State is in memory and single-threaded. Redaction is pattern based. Request and confirmation IDs are sequential, but a non-owner learns nothing from guessing them. The full list is in the README and `docs/day6_threat_model.md`.

## 8. For the instructor, before class

- [ ] On a **fresh clone** (not your working copy), do sections 1 to 3 on one macOS and one Windows machine. The Windows PowerShell commands in this checklist were written on a machine without PowerShell and have **not** been run there.
- [ ] Confirm every student can open the repository URL above (access and visibility were not verified by the author).
- [ ] Remind students to use **EMP002** for VPN ticket demos in the chat: EMP001, EMP003 and EMP004 already have an open VPN ticket, so the agent shows it instead of proposing a new one.
