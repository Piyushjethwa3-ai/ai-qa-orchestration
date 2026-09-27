"""
Baseline tests for GET /tickets/{ticket_id}.

Includes the required ticket-ownership test (BR02) and one example of
validating a ticket against schemas/ticket.schema.json. Day 1/Day 2
exercises can add cases for a missing ticket (BR03, expect 404) and a
missing/unknown demo employee header (BR01, expect 400).
"""

import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "ticket.schema.json"


def test_get_own_ticket_returns_200(client):
    response = client.get("/tickets/TCK-1001", headers={"X-Demo-Employee-ID": "EMP001"})

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "TCK-1001"


def test_get_other_employees_ticket_returns_403(client):
    # TCK-1001 belongs to EMP001, so EMP002 must not be able to view it.
    response = client.get("/tickets/TCK-1001", headers={"X-Demo-Employee-ID": "EMP002"})

    assert response.status_code == 403


def test_ticket_matches_schema(client):
    response = client.get("/tickets/TCK-1001", headers={"X-Demo-Employee-ID": "EMP001"})
    ticket = response.json()

    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    # Raises jsonschema.exceptions.ValidationError if the ticket is invalid.
    jsonschema.validate(instance=ticket, schema=schema)

def test_missing_ticket_returns_404(client):
    response = client.get("/tickets/TCK-9999", headers={"X-Demo-Employee-ID": "EMP001"})

    assert response.status_code == 404