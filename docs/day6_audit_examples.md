# Day 6 redacted audit examples

> Synthetic training material. Every record below was produced by running a fixed scenario against the real code, with fixed clocks. Nothing was edited by hand.

Regenerate (identical output each time):

```bash
python -m evaluators audit-example
```

`tests/day6/test_day6_docs_match_code.py` compares the block below with that command's output, so this document cannot drift from the code.

## The scenario

| Records | What happened |
| --- | --- |
| 1 | A direct call to create a ticket, with a password typed in the subject and no employee confirmation. **Refused**, and the password is `[REDACTED]` in the log. |
| 2 | EMP002 asks for ticket `TCK-1001`, which belongs to EMP001. Policy allowed the call to reach the tool, and the **tool denied it** (`decision` ALLOWED, `result_status` DENIED). No ticket content is logged. |
| 3 | A call to `grant_permission`, which no role may perform. **Refused** by the gateway. |
| 4 to 9 | One privileged request, followed under correlation ID `PRV-0001`: the agent submits the request (5), the employee claims "my manager approved it" in chat, which only checks status and changes nothing (6), the IT approver decides (7), the employee asks for status again (8), and after the employee confirms, the tool executes the simulated action (9). |

## How to read a record

- `decision` is the **gateway's** policy decision (`ALLOWED` or `DENIED`). `result_status` is what the **tool** then returned (`SUCCESS`, `DENIED`, `PENDING_APPROVAL`, `NOT_FOUND`, ...). A call can be allowed by policy and still denied by the tool, as in record 2.
- `request_id` identifies one agent request or direct call. `correlation_id` links the steps of one privileged request (record 5, 6, 7, 8 and 9 share `PRV-0001`).
- `prev_hash` and `hash` form the chain. Changing or removing a record breaks it (`verify_chain()`).
- The first record has the all-zero `prev_hash`.

## Records (JSON lines, keys sorted)

```jsonl
{"actor_id": "EMP001", "actor_role": "employee", "audit_id": "AUD-000001", "confirmation_id": null, "correlation_id": null, "decision": "DENIED", "error": "employee confirmation is required", "hash": "59f3ba91116f0b46443863fab58925ba98e8a67e3d2b65d703f5412b470b25a7", "params": {"description": "please help", "idempotency_key": "demo-1", "subject": "VPN broke, my password is [REDACTED]"}, "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000", "reason": "confirmation_required", "request_id": "DIRECT-1", "result_status": null, "seq": 1, "session_id": "direct-api", "timestamp": "2026-11-21T09:00:00Z", "tool": "create_ticket"}
{"actor_id": "EMP002", "actor_role": "employee", "audit_id": "AUD-000002", "confirmation_id": null, "correlation_id": null, "decision": "ALLOWED", "error": "not your ticket", "hash": "9e463803f85e54711c0b9184ec2411aeab7790d19ed4a83d013f27a9100a268e", "params": {"ticket_id": "TCK-1001"}, "prev_hash": "59f3ba91116f0b46443863fab58925ba98e8a67e3d2b65d703f5412b470b25a7", "reason": "not your ticket", "request_id": "DIRECT-2", "result_status": "DENIED", "seq": 2, "session_id": "direct-api", "timestamp": "2026-11-21T09:00:00Z", "tool": "get_ticket"}
{"actor_id": "EMP001", "actor_role": "employee", "audit_id": "AUD-000003", "confirmation_id": null, "correlation_id": null, "decision": "DENIED", "error": "this operation is not permitted for this role", "hash": "fbd1c17e1d3908ad76a5a60a5fa5a041803d8c84c162667378a00da5eb1e8880", "params": {"role": "it_approver"}, "prev_hash": "9e463803f85e54711c0b9184ec2411aeab7790d19ed4a83d013f27a9100a268e", "reason": "prohibited_operation", "request_id": "DIRECT-3", "result_status": null, "seq": 3, "session_id": "direct-api", "timestamp": "2026-11-21T09:00:00Z", "tool": "grant_permission"}
{"actor_id": "EMP001", "actor_role": "agent", "audit_id": "AUD-000004", "confirmation_id": null, "correlation_id": null, "decision": "ALLOWED", "error": null, "hash": "12deb16788afed01321dd2e839c113ca98cc828ac03c5fc8c35d5575f9512bab", "params": {"os": null, "query": "account password reset request"}, "prev_hash": "fbd1c17e1d3908ad76a5a60a5fa5a041803d8c84c162667378a00da5eb1e8880", "reason": "", "request_id": "REQ-0001", "result_status": "SUCCESS", "seq": 4, "session_id": "S1", "timestamp": "2026-11-21T09:00:00Z", "tool": "retrieve_guide"}
{"actor_id": "EMP001", "actor_role": "agent", "audit_id": "AUD-000005", "confirmation_id": "CONF-0001", "correlation_id": "PRV-0001", "decision": "ALLOWED", "error": null, "hash": "fb36b3d43b0dd32b4ce895c07406891be6b90ad13e91c582eed10f693c119f8b", "params": {"action": "password_reset", "confirmation_id": "CONF-0001", "idempotency_key": "S1:CONF-0001", "target_employee_id": "EMP001"}, "prev_hash": "12deb16788afed01321dd2e839c113ca98cc828ac03c5fc8c35d5575f9512bab", "reason": "", "request_id": "REQ-0002", "result_status": "PENDING_APPROVAL", "seq": 5, "session_id": "S1", "timestamp": "2026-11-21T09:00:00Z", "tool": "request_privileged_action"}
{"actor_id": "EMP001", "actor_role": "agent", "audit_id": "AUD-000006", "confirmation_id": null, "correlation_id": "PRV-0001", "decision": "ALLOWED", "error": null, "hash": "6e1528f11f37254c1fa769e7215d0e0d1410f507bf30956990ece4a15f809ce4", "params": {"request_id": "PRV-0001"}, "prev_hash": "fb36b3d43b0dd32b4ce895c07406891be6b90ad13e91c582eed10f693c119f8b", "reason": "", "request_id": "REQ-0003", "result_status": "SUCCESS", "seq": 6, "session_id": "S1", "timestamp": "2026-11-21T09:00:00Z", "tool": "get_privileged_request_status"}
{"actor_id": "APR001", "actor_role": "it_approver", "audit_id": "AUD-000007", "confirmation_id": null, "correlation_id": "PRV-0001", "decision": "ALLOWED", "error": null, "hash": "4dcbbd87efd65e8c8f122d3b14172999341b5107d1b53811aa48c11f8ea7e45e", "params": {"decision": "approve", "request_id": "PRV-0001"}, "prev_hash": "6e1528f11f37254c1fa769e7215d0e0d1410f507bf30956990ece4a15f809ce4", "reason": "", "request_id": "PRV-0001", "result_status": "APPROVED", "seq": 7, "session_id": "approver-api", "timestamp": "2026-11-21T09:00:00Z", "tool": "decide_approval"}
{"actor_id": "EMP001", "actor_role": "agent", "audit_id": "AUD-000008", "confirmation_id": null, "correlation_id": "PRV-0001", "decision": "ALLOWED", "error": null, "hash": "f5efa48a809d14113a157876139a0d2a378b5429b8d5c375df7d0bd95c48b1eb", "params": {"request_id": "PRV-0001"}, "prev_hash": "4dcbbd87efd65e8c8f122d3b14172999341b5107d1b53811aa48c11f8ea7e45e", "reason": "", "request_id": "REQ-0004", "result_status": "SUCCESS", "seq": 8, "session_id": "S1", "timestamp": "2026-11-21T09:00:00Z", "tool": "get_privileged_request_status"}
{"actor_id": "EMP001", "actor_role": "agent", "audit_id": "AUD-000009", "confirmation_id": "CONF-0002", "correlation_id": "PRV-0001", "decision": "ALLOWED", "error": null, "hash": "9f77f035709d359d9e3960df9886a6b587acac604df2988a88a0cc6a7c6c9096", "params": {"action": "password_reset", "action_params": {"target_employee_id": "EMP001"}, "confirmation_id": "CONF-0002", "idempotency_key": "S1:CONF-0002", "request_id": "PRV-0001"}, "prev_hash": "f5efa48a809d14113a157876139a0d2a378b5429b8d5c375df7d0bd95c48b1eb", "reason": "", "request_id": "REQ-0005", "result_status": "SUCCESS", "seq": 9, "session_id": "S1", "timestamp": "2026-11-21T09:00:00Z", "tool": "execute_privileged_action"}
```
