"""
Day 2 fixtures, layered on top of the existing `client` fixture in
tests/conftest.py (pytest shares parent conftest fixtures automatically).
"""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


@pytest.fixture()
def auth_headers():
    """Return a factory that builds the demo auth header for one employee.

    Usage: client.get(url, headers=auth_headers("EMP001"))
    """

    def _auth_headers(employee_id: str) -> dict:
        return {"X-Demo-Employee-ID": employee_id}

    return _auth_headers


@pytest.fixture()
def validate_against_schema():
    """Return a function that validates a response body against one of
    this project's JSON Schema contract files in schemas/.

    Usage: validate_against_schema(response.json(), "ticket.schema.json")

    Raises jsonschema.exceptions.ValidationError if the body doesn't
    satisfy that schema's required fields, types, or other constraints
    -- that exception is what fails the calling test, so no manual
    field-by-field assertions are needed for the shape check itself.
    """

    def _validate(instance: dict, schema_filename: str) -> None:
        schema_path = SCHEMAS_DIR / schema_filename
        with open(schema_path, "r", encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
        jsonschema.validate(instance=instance, schema=schema)

    return _validate
