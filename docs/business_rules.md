# Business Rules — Week 1 Service Desk API

These rules describe how the Northstar Services IT Service Desk API is
expected to behave. They exist so that tests have something authoritative
to check against, and so that later weeks (AI responses, RAG, agents) have
a stable baseline they must not violate.

## BR01 — The demo employee comes from the header, not from text

The "current employee" for a request is always taken from the
`X-Demo-Employee-ID` request header. It is never inferred from a request
body, a query string, or any free-text field.

- If the header is missing, the API returns `400 Bad Request`.
- If the header value does not match a known employee, the API returns
  `400 Bad Request`.

Implemented in: [`app/main.py`](../app/main.py) (`get_current_employee`),
using [`app/rules.py`](../app/rules.py) (`find_employee_by_id`).

## BR02 — An employee cannot view another employee's ticket

A ticket belongs to exactly one employee (`ticket["employee_id"]`). A
request for `GET /tickets/{ticket_id}` must return `403 Forbidden` when
the ticket exists but belongs to a different employee than the one
identified by `X-Demo-Employee-ID`.

Implemented in: [`app/rules.py`](../app/rules.py) (`employee_owns_ticket`),
enforced in [`app/main.py`](../app/main.py) (`get_ticket`).

## BR03 — A missing ticket returns 404

If no ticket with the requested `ticket_id` exists at all, the API
returns `404 Not Found`. This check happens before the ownership check
(BR02): a ticket that does not exist is "not found," not "forbidden."

Implemented in: [`app/rules.py`](../app/rules.py) (`find_ticket_by_id`),
enforced in [`app/main.py`](../app/main.py) (`get_ticket`).

## BR04 — VPN service status has a defined status and update time

`GET /services/vpn/status` always returns a response containing:

- `status`: one of `operational`, `degraded`, or `outage`.
- `updated_at`: an ISO 8601 timestamp indicating when the status was last
  updated.

Implemented in: [`data/service_status.json`](../data/service_status.json),
served by [`app/main.py`](../app/main.py) (`get_vpn_status`).
