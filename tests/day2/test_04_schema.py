"""
Day 2, part 4: JSON Schema validation of real API responses.

Reusable validation: `validate_against_schema` (defined in
tests/day2/conftest.py) loads one of this project's schema files from
schemas/ and runs `jsonschema.validate` against a response body. Every
API test below calls it the same way:

    validate_against_schema(response.json(), "some.schema.json")

which raises `jsonschema.exceptions.ValidationError` if the body
doesn't match -- that raised exception is what fails the test, not a
manual field-by-field comparison written in this file.

## JSON Schema keywords used here, explained for beginners

- `"type": "object"` -- the value being checked must be a JSON object
  (a Python dict, once parsed), not a list, string, or number.
- `"properties"` -- a map from each expected field name to its own
  small schema. `"properties": {"status": {"type": "string"}}` means
  "IF there's a field called status, it must be a string" -- but by
  itself, `properties` does not make a field mandatory.
- `"required"` -- the list of field names that MUST be present. This
  is what actually makes a field mandatory; `properties` only
  describes a field's shape once it's known to be there.
- `"type": "string"` (inside a property's own schema) -- that specific
  field's value must be text, not a number, boolean, list, or null.
  This is exactly what catches `wrong-status-type` below: a "status"
  field with the *right key* but the *wrong kind of value* (e.g. an
  int) still fails validation, even though `required` alone would
  already have been satisfied by the key being present.

## The 4 real API response categories covered here

1. Employee profile -- GET /employees/me            -> employee.schema.json
2. Ticket             -- GET /tickets/{ticket_id}     -> ticket.schema.json
3. Service status     -- GET /services/vpn/status     -> service_status.schema.json
4. Error response      -- GET /tickets/{ticket_id}, missing ticket (404) -> error.schema.json

Every test asserts the expected HTTP status code FIRST, and only then
validates the body against a schema. Validating an error body against
a success schema (or vice versa) would be a check against the wrong
contract and could pass or fail for the wrong reason.

## Fault injection: --day2-fault=missing-status / wrong-status-type

Both target BR04 (`GET /services/vpn/status`'s "status" field) by
monkeypatching `app.data.load_service_status` -- the function
`get_vpn_status` in app/main.py calls to build its response -- so each
fault is injected in the application's own response-generation path,
not by editing the response object inside a test after the fact.
`get_vpn_status` itself is never touched or aware anything changed.

Whether FastAPI's own response handling catches either fault before
jsonschema gets a chance: it does not, and that is confirmed by running
both faults (see the instructor map for the actual command output).
Neither route in this app declares a `response_model=`, only a plain
`-> dict` return-type hint, and FastAPI does not validate outgoing
responses against a bare `dict` annotation -- it only serializes
whatever the function returns. Both `missing-status` and
`wrong-status-type` are ordinary JSON-serializable values (a dict
missing a key, and an int in place of a string), so the framework
serializes and returns them as an ordinary 200 with no complaint.
jsonschema, run explicitly by this test file, is the only layer that
catches either fault -- which is exactly the point of writing schema
tests instead of relying on the framework alone.
"""

import jsonschema
import pytest

from app import data


@pytest.fixture(autouse=True)
def _maybe_break_service_status_response(request, monkeypatch):
    """Apply --day2-fault=missing-status / wrong-status-type, scoped to
    this file only.

    No-op (BR04 stays fully intact) unless one of those two values was
    passed. When one was, this replaces `app.data.load_service_status`
    -- the data-loading step `get_vpn_status` depends on -- with a fake
    that returns a malformed copy of the real payload. The real
    `data/service_status.json` file on disk is read fresh and then
    copied in memory each time; it is never written to, so persisted
    data is untouched. monkeypatch reverts the swap automatically the
    instant each test function returns.
    """
    fault = request.config.getoption("--day2-fault")

    if fault == "missing-status":

        def _load_service_status_missing_status():
            broken = dict(data.load_json_file("service_status.json"))
            del broken["status"]
            return broken

        monkeypatch.setattr(data, "load_service_status", _load_service_status_missing_status)

    elif fault == "wrong-status-type":

        def _load_service_status_wrong_type():
            broken = dict(data.load_json_file("service_status.json"))
            broken["status"] = 1  # should be a string, e.g. "operational"
            return broken

        monkeypatch.setattr(data, "load_service_status", _load_service_status_wrong_type)


def test_employee_profile_matches_schema(client, auth_headers, validate_against_schema):
    # Arrange / Act
    response = client.get("/employees/me", headers=auth_headers("EMP001"))

    # Assert: expected status first, then the contract.
    assert response.status_code == 200
    validate_against_schema(response.json(), "employee.schema.json")


def test_ticket_matches_schema(client, auth_headers, validate_against_schema):
    # Arrange / Act
    response = client.get("/tickets/TCK-1001", headers=auth_headers("EMP001"))

    # Assert: expected status first, then the contract.
    assert response.status_code == 200
    validate_against_schema(response.json(), "ticket.schema.json")


def test_service_status_matches_schema(client, validate_against_schema):
    # Arrange / Act: no auth header -- /services/vpn/status is unprotected.
    response = client.get("/services/vpn/status")

    # Assert: expected status first, then the contract. This is the
    # test the two fault-injection flags above are aimed at.
    assert response.status_code == 200
    validate_against_schema(response.json(), "service_status.schema.json")


def test_missing_ticket_error_matches_schema(client, auth_headers, validate_against_schema):
    # Arrange / Act: the "relevant error response" case -- BR03's 404
    # for a well-formed but nonexistent ticket id.
    response = client.get("/tickets/TCK-9999", headers=auth_headers("EMP001"))

    # Assert: expected status first, then the contract.
    assert response.status_code == 404
    validate_against_schema(response.json(), "error.schema.json")


def test_beginner_schema_example_missing_required_field():
    """Not an API case -- do not count this toward the 4 categories
    above. A small, hand-built dict, shown only so a beginner can see
    what `required` enforces in isolation, before trusting it against a
    real response.
    """
    schema = {
        "type": "object",
        "required": ["employee_id", "full_name"],
        "properties": {
            "employee_id": {"type": "string"},
            "full_name": {"type": "string"},
        },
    }
    incomplete_profile = {"employee_id": "EMP001"}  # full_name is missing

    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(instance=incomplete_profile, schema=schema)
