"""
Structural checks for one assistant response.

"Structural" means: can the application read this response? It is valid
JSON, it is one object, and it matches schemas/day3_response.schema.json
(exactly four keys, correct types, an allowed status value).

What these checks can NOT tell you: whether the answer agrees with the
approved context, whether a recovery time was invented, or whether it is
safe. A response can pass every check here and still be wrong. That part
is the human rubric's job (see assessment.py).

Nothing here repairs a bad response. Invalid JSON, a wrong type or an
extra key is recorded as a finding and the structure result is FAIL.
"""

import json

import jsonschema

from day3_lab.paths import RESPONSE_SCHEMA_PATH

STATUS_VALUES = ("operational", "degraded", "outage", "unknown")


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key, e.g. two "answer" fields."""


def _reject_duplicate_keys(pairs: list) -> dict:
    # Python's json module normally keeps the LAST duplicate silently.
    # That would hide a malformed response, so reject it instead.
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"Duplicate key in JSON object: {key!r}")
        result[key] = value
    return result


def _reject_non_standard_constant(name: str):
    # json.loads accepts NaN and Infinity by default; standard JSON does not.
    raise ValueError(f"Non-standard JSON constant: {name}")


def load_response_schema() -> dict:
    with open(RESPONSE_SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def check_structure(raw_response: str | None, schema: dict | None = None) -> tuple[dict | None, dict]:
    """Parse and validate one raw response.

    Returns (parsed_response, structural) where:
    - parsed_response is the decoded JSON value, or None if it would not parse
    - structural is {"result": "PASS"|"FAIL"|"NOT_RUN", "parse_ok", "schema_ok", "findings": [...]}
    """
    if raw_response is None:
        return None, {
            "result": "NOT_RUN",
            "parse_ok": False,
            "schema_ok": False,
            "findings": [
                {"stage": "provider", "path": "", "message": "No response text was received, so nothing was validated."}
            ],
        }

    try:
        parsed = json.loads(
            raw_response,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_standard_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return None, {
            "result": "FAIL",
            "parse_ok": False,
            "schema_ok": False,
            "findings": [{"stage": "parse", "path": "", "message": str(exc)}],
        }

    validator = jsonschema.Draft7Validator(schema or load_response_schema())
    findings = []
    # Collect EVERY schema error (not just the first) so the report shows them all.
    for error in sorted(validator.iter_errors(parsed), key=lambda e: [str(p) for p in e.absolute_path]):
        findings.append(
            {
                "stage": "schema",
                "path": "/".join(str(part) for part in error.absolute_path) or "(root)",
                "keyword": error.validator,
                "message": error.message,
            }
        )

    return parsed, {
        "result": "PASS" if not findings else "FAIL",
        "parse_ok": True,
        "schema_ok": not findings,
        "findings": findings,
    }
