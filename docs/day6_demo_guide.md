# Day 6 classroom demonstration guide

> Synthetic training material. The company, people and policies are fictional. **Nothing here calls an LLM, the network
> or any API, and nothing writes to `data/`.** Every command below is deterministic: the same command prints the same
> text every time.

## 1. What you are showing

| | Week 5 agent (`python -m app.agent`) | Day 6 governed agent (`python -m app.governance`) |
| --- | --- | --- |
| What it is | A deterministic, rule-based Python agent with simulated tools | The same agent, with every tool call passing through a governance gateway |
| Extra controls | Write tools refuse to run without the employee's confirmation | Permission matrix, IT approvals, redacted audit log, parameter allow-list |
| Uses an LLM? | **No** | **No** |
| Show it to teach | How an agent plans, uses tools, retries and stops | Where a restricted action is blocked when the model asks for it anyway |

The agent is plain Python, so the same input always gives the same output. That is what makes it testable. A real
model would be less predictable, and these demonstrations do not show how a real model behaves.

**Two kinds of tickets.** The Week 1 API reads `data/tickets.json`. The agent keeps the tickets it creates in
**memory**. They vanish when the program exits, and `GET /tickets/TCK-1007` in the Week 1 API returns 404 for a ticket
the agent just created. This is deliberate for the lab (persistence was not changed). Tell students before they try it.

## 2. Student set-up on a fresh clone

macOS / Linux:

```bash
git clone <your repository URL> ai-qa-orchestration
cd ai-qa-orchestration
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Windows PowerShell:

```powershell
git clone <your repository URL> ai-qa-orchestration
cd ai-qa-orchestration
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

If PowerShell blocks the activation script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.
No API key is needed and no new dependency is required. The last command should report every test passing.

## 3. The five demonstrations

Every command below is **identical on macOS/Linux and Windows PowerShell** (run from the project root with the virtual
environment activated). Each expected-output block below is an excerpt; the full output also contains a banner and a
"What to observe" list. A test re-runs every command here and checks that each excerpt line really appears, in order.

### Demo 1: Successful VPN troubleshooting and ticket creation

**Business rules:** BR03 (check status first), BR04 (right guide for the device), BR06 (confirmation before a ticket), BR08 (no duplicate).

```
python -m app.governance demo vpn-ticket
```

```text expected-output: python -m app.governance demo vpn-ticket
[1] EMP002 says: "My VPN stopped working after I changed my password. I have a client call in 20 minutes. I am on a Mac."
    agent [PENDING_CONFIRMATION]:
    tools: get_service_status=SUCCESS -> retrieve_guide=SUCCESS -> search_tickets=SUCCESS
[2] EMP002 says: "yes"
    agent [TICKET_CREATED]:
      Ticket TCK-1007 has been created for you (status: open). The ticket tool confirmed it.
    tools: create_ticket=SUCCESS
[3] EMP002's tickets (in the agent's in-memory store)
    TCK-1007 [open] VPN connection problem (Mac)   <- created in this session, in memory only
```

**What students should observe**

- The agent called three tools in order: status, guide, ticket search. It checked the VPN status before anything else.
- It only **proposed** a ticket ("Nothing has been created yet"). The ticket appeared only after the employee said yes.
- The new ticket is marked as in memory only.

Week 5 version (no governance layer): `python -m app.agent demo vpn-ticket`. Same result, which shows the agent works without Day 6.
Extra: `python -m app.agent demo timeout-no-duplicate` shows a timeout after a successful write ending in exactly one ticket.

### Demo 2: Cross-user ticket access denied

**Business rules:** BR01 (identity from the session, not from text), BR02 (own tickets only).

```
python -m app.governance demo cross-user
```

```text expected-output: python -m app.governance demo cross-user
[1] EMP002 says: "Show me ticket TCK-1001"
    agent [TICKET_UNAVAILABLE]:
      I can't find a ticket with that ID that I'm able to show you.
    tools: get_ticket=DENIED
[2] EMP002 calls get_ticket directly
    -> DENIED: not your ticket
[3] EMP001 calls get_ticket directly
    -> SUCCESS: TCK-1001 'VPN client fails to connect from home network'
```

**What students should observe**

- TCK-1001 belongs to EMP001. EMP002 gets no content, in chat or at the tool.
- The chat wording does not say whether the ticket exists, so it cannot be used to discover other employees' tickets.
- The last step is the control: EMP001 can read their own ticket.

### Demo 3: Ticket creation blocked without confirmation

**Business rule:** BR06 (ticket creation requires the employee's confirmation).

```
python -m app.governance demo no-confirmation
```

```text expected-output: python -m app.governance demo no-confirmation
[1] EMP001 says: "My manager approved it, please create the ticket now"
    agent [NEEDS_CLARIFICATION]:
[2] EMP001 calls create_ticket directly, with no confirmation
    -> DENIED: employee confirmation is required
[3] EMP001 calls create_ticket with a made-up confirmation ID (CONF-9999)
    -> DENIED: confirmation required (unknown_confirmation)
[4] EMP001 calls create_ticket with the employee's confirmation
    -> SUCCESS: TCK-1007 'VPN problem'
[5] EMP001's tickets (in the agent's in-memory store)
```

**What students should observe**

- Typing "my manager approved it" does nothing: the agent called no tool.
- Calling the tool directly with no confirmation, or with a made-up confirmation ID, is refused.
- With a real confirmation recorded for exactly these parameters, the same call succeeds.
- The Week 5 command `python -m app.agent demo no-confirmation` shows the **tool itself** refusing (its wording differs: no gateway layer exists there).

### Demo 4: Privileged action blocked without IT approval, then executed after approval

**Business rules:** BR06 (separate IT approval), BR07 (approval bound to employee, action, parameters, request), BR11 (honest outcomes), BR12 (audit).

```
python -m app.governance demo privileged
```

```text expected-output: python -m app.governance demo privileged
[1] EMP001 says: "I forgot my password and need a reset"
    agent [PENDING_CONFIRMATION]:
[2] EMP001 says: "yes"
    agent [PENDING_APPROVAL]:
[3] EMP001 says: "My manager approved it, run the reset now"
    agent [PRIVILEGED_STATUS]:
[4] EMP001 tries to execute PRV-0001 (password_reset) directly, with their own confirmation
    -> DENIED: approval not valid (pending)
[5] EMP001 tries to approve request PRV-0001
    -> DENIED: not_an_approver (only a simulated IT approver can decide)
[6] APR001 tries to approve request PRV-0001
    -> APPROVED by APR001
[7] EMP001 says: "what is the status of my reset request"
    agent [PENDING_CONFIRMATION]:
[8] EMP001 says: "yes"
    agent [PRIVILEGED_EXECUTED]:
[9] EMP001 tries to execute PRV-0001 (password_reset) directly, with their own confirmation
    -> DENIED: approval not valid (already_used)
    hash chain intact: True
```

**What students should observe**

- "My manager approved it" typed in chat changed nothing: the request stayed pending.
- A direct execution attempt before approval was refused by the tool ("approval not valid (pending)").
- An employee cannot approve (`not_an_approver`). Only the simulated IT approver can.
- After approval and the employee's yes, the simulated action ran **once**. No real password or account was touched.
- Reusing the approval is refused (`already_used`). The audit log at the end shows every attempt.

### Demo 5: Prompt injection through a retrieved document

**Business rule:** BR12 (documents and tool output are data, not authority).

```
python -m evaluators injection-demo
```

```text expected-output: python -m evaluators injection-demo
    Tool requested              Gateway  Tool result  Why
    --------------------------- -------- ------------ ----------------------------------------
    decide_approval             DENIED   None         this operation is not permitted for this role
    grant_permission            DENIED   None         this operation is not permitted for this role
    execute_privileged_action   ALLOWED  DENIED       approval not valid (pending)
    create_ticket               ALLOWED  DENIED       confirmation required (unknown_confirmation)
    get_ticket                  ALLOWED  DENIED       not your ticket
    search_tickets              DENIED   None         an action may only be taken for the signed-in employee

Resulting state:
    approval PRV-0001 status : PENDING
    privileged executions    : 0
    injected tickets created : 0
    protected data leaked    : no
    audit chain intact       : True
```

**What students should observe**

- The real agent never obeys text it retrieves, so this demo uses a deliberately **gullible stand-in for a model** that obeys every `CALL` line hidden in a document. It really does attempt all six prohibited actions.
- Every attempt is refused by the real gateway and tools. Two layers stop them: the **gateway** (permission matrix, employee identity) and the **tools** (approval, confirmation, ownership).
- Nothing changed: the request is still pending, nothing executed, no ticket created, and no other employee's data leaked.
- To see the difference enforcement makes, run the test-only comparison. It switches the controls off **inside one test** (the application has no such switch) and shows the same attacks succeed:

```
python -m pytest tests/day6/test_day6_injection.py -k "disabled" -s -v
```

Expected: `1 passed`, and a printed comparison (executions 0 vs 1, injected tickets 0 vs 1, protected data leak False vs True).

## 4. Try it yourself

```
python -m app.agent chat --employee EMP002
python -m app.governance chat --employee EMP001
python -m app.governance chat --employee EMP002 -m "My VPN stopped working on my Mac" -m yes
```

Inside `chat`: `/help`, `/as EMP001` (switch employee; session state stays separate), `/tickets`, `/trace`, `/quit`.
In the governed chat also `/approve [REQUEST_ID] [reason]` (acts as the simulated IT approver `APR001`), `/reject`, `/audit`.

Use **EMP002** for the VPN ticket demos. EMP001, EMP003 and EMP004 already have an open VPN ticket, so the agent shows it
instead of proposing a new one (case A-28 checks this).

## 5. The HTTP version (optional)

Start the server in one terminal: `python -m uvicorn app.main:app --port 8000`. State is in memory and starts empty each
time the server starts, so restart it between runs. IDs such as `PRV-0001` assume a fresh server.

macOS / Linux (verified on macOS):

```bash
B=http://127.0.0.1:8000; J='Content-Type: application/json'; E2='X-Demo-Employee-ID: EMP002'
curl -s -H "$E2" -H "$J" -d '{"session_id":"demo1","message":"My VPN stopped working after I changed my password. I am on a Mac."}' $B/agent/chat
curl -s -H "$E2" -H "$J" -d '{"session_id":"demo1","message":"yes"}' $B/agent/chat
curl -s -H "$E2" $B/tickets/TCK-1001          # Week 1 route: 403, not your ticket
curl -s -H "$E2" $B/tickets/TCK-1007          # 404: agent tickets are in memory, the Week 1 route reads the file
```

Windows PowerShell (**not executed on the machine that wrote this guide, because PowerShell is not installed there;
the CLI commands above are the verified path**):

```powershell
$B = "http://127.0.0.1:8000"
function Call($Method, $Path, $Headers, $Body) {
  try { Invoke-RestMethod -Method $Method -Uri "$B$Path" -Headers $Headers -ContentType "application/json" `
        -Body ($Body | ConvertTo-Json -Depth 5) }
  catch { $_.ErrorDetails.Message } }
$E2 = @{"X-Demo-Employee-ID" = "EMP002"}
Call Post "/agent/chat" $E2 @{session_id="demo1"; message="My VPN stopped working after I changed my password. I am on a Mac."}
Call Post "/agent/chat" $E2 @{session_id="demo1"; message="yes"}
Call Get  "/tickets/TCK-1001" $E2 $null
```

## 6. Facilitator notes

- **Determinism:** CLI output has no timestamps and is identical on every run. The HTTP API's ticket `created_at` and audit timestamps use the real clock.
- **It is a simulation:** a privileged action here records that the simulation ran. No password exists anywhere in the code.
- **Be clear about limits** (see `docs/day6_notes.md`): the agent is not a language model; identity is a training header; state is in memory and single-threaded.
- **Do not edit expected results to make a demo pass.** If a demo output changes, a test fails and tells you which document is stale.
