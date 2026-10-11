"""
Day 3: structural checks on one response (JSON + response schema).

These tests only prove that the application can READ a response. None of
them claims a response is correct or safe.
"""

import json

import pytest

from day3_lab.validation import check_structure

VALID = {
    "answer": "There is a confirmed VPN outage. No recovery time has been published yet.",
    "service_status": "outage",
    "recovery_time": None,
    "next_step": "Wait for an official service-status update.",
}


def _check(obj):
    return check_structure(json.dumps(obj))


def test_valid_response_passes_structure():
    parsed, structural = _check(VALID)

    assert structural["result"] == "PASS"
    assert structural["findings"] == []
    assert parsed == VALID


def test_recovery_time_may_be_a_string():
    _, structural = _check({**VALID, "recovery_time": "About 45 minutes; estimate only"})

    assert structural["result"] == "PASS"


@pytest.mark.parametrize("missing", ["answer", "service_status", "recovery_time", "next_step"])
def test_missing_field_fails(missing):
    response = {key: value for key, value in VALID.items() if key != missing}

    _, structural = _check(response)

    assert structural["result"] == "FAIL"
    assert any(missing in finding["message"] for finding in structural["findings"])


def test_extra_field_fails():
    _, structural = _check({**VALID, "confidence": 0.99})

    assert structural["result"] == "FAIL"
    assert any(f["keyword"] == "additionalProperties" for f in structural["findings"])


@pytest.mark.parametrize(
    "field, wrong_value",
    [
        pytest.param("answer", 42, id="answer_is_number"),
        pytest.param("answer", None, id="answer_is_null"),
        pytest.param("recovery_time", 30, id="recovery_time_is_number"),
        pytest.param("next_step", ["call the desk"], id="next_step_is_list"),
        pytest.param("service_status", True, id="status_is_boolean"),
    ],
)
def test_wrong_type_fails(field, wrong_value):
    _, structural = _check({**VALID, field: wrong_value})

    assert structural["result"] == "FAIL"
    assert any(f["path"] == field for f in structural["findings"])


@pytest.mark.parametrize("status", ["down", "Outage", "OUTAGE", "", "operational "])
def test_invalid_status_enum_fails_without_coercion(status):
    # "Outage" is NOT lower-cased into "outage"; invalid values stay invalid.
    _, structural = _check({**VALID, "service_status": status})

    assert structural["result"] == "FAIL"


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_or_blank_answer_fails(text):
    _, structural = _check({**VALID, "answer": text})

    assert structural["result"] == "FAIL"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("The VPN is down.", id="plain_text"),
        pytest.param('{"answer": "x", ', id="truncated_json"),
        pytest.param(json.dumps([VALID]), id="array_not_object"),
        pytest.param("", id="empty_string"),
    ],
)
def test_unreadable_response_fails_and_keeps_evidence(raw):
    parsed, structural = check_structure(raw)

    assert structural["result"] == "FAIL"
    assert structural["findings"], "a finding explaining the failure must be recorded"
    if not structural["parse_ok"]:
        assert parsed is None


def test_duplicate_keys_are_rejected_not_silently_merged():
    raw = (
        '{"answer": "Fixed in 30 minutes.", "answer": "No ETA published.", '
        '"service_status": "outage", "recovery_time": null, "next_step": "Wait."}'
    )

    parsed, structural = check_structure(raw)

    assert structural["result"] == "FAIL"
    assert parsed is None
    assert "Duplicate key" in structural["findings"][0]["message"]


def test_all_schema_errors_are_reported_not_just_the_first():
    _, structural = _check({"answer": 1, "service_status": "down", "extra": True})

    assert len(structural["findings"]) >= 4  # wrong type, bad enum, extra key, missing keys


def test_valid_enum_does_not_prove_status_matches_context():
    # D3-01's approved context says "outage". "operational" is a VALID enum
    # value, so the structure passes. Catching the contradiction with the
    # supplied facts is a human-review job, which is why outcome stays pending.
    _, structural = _check({**VALID, "service_status": "operational"})

    assert structural["result"] == "PASS"
