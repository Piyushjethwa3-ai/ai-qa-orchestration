"""
Day 3: the supplied dataset and rubric are valid and were copied unchanged.
"""

import json
import shutil

import pytest

from day3_lab import paths
from day3_lab.dataset import DIMENSIONS, load_cases, load_rubric, validate_data


def test_supplied_dataset_is_valid_with_ten_unique_cases():
    result = validate_data()

    assert result["problems"] == []
    assert result["case_count"] == 10
    case_ids = [case["case_id"] for case in load_cases()["cases"]]
    assert len(set(case_ids)) == 10


def test_validate_data_command_prints_count_10(run_cli):
    code, out, _ = run_cli("validate-data")

    assert code == 0
    assert "count 10" in out


def test_rubric_dimension_order_matches_review_score_order():
    assert load_rubric()["dimension_order"] == list(DIMENSIONS)


@pytest.mark.skipif(not paths.SOURCE_CASES_PATH.exists(), reason="day3_materials/ not supplied")
def test_lab_copies_are_byte_identical_to_supplied_materials():
    assert paths.CASES_PATH.read_bytes() == paths.SOURCE_CASES_PATH.read_bytes()
    assert paths.RUBRIC_PATH.read_bytes() == paths.SOURCE_RUBRIC_PATH.read_bytes()


def _copy_inputs(tmp_path):
    """Copy every input to tmp_path so a test can break one without touching the real files."""
    copies = {}
    for name, source in {
        "cases": paths.CASES_PATH,
        "rubric": paths.RUBRIC_PATH,
        "mock": paths.MOCK_RESPONSES_PATH,
        "clinic": paths.CLINIC_FIXTURES_PATH,
    }.items():
        copies[name] = tmp_path / source.name
        shutil.copy(source, copies[name])
    return copies


def _validate(copies, source_cases=None):
    return validate_data(
        cases_path=copies["cases"],
        rubric_path=copies["rubric"],
        mock_path=copies["mock"],
        clinic_path=copies["clinic"],
        source_cases_path=source_cases or paths.SOURCE_CASES_PATH,
        source_rubric_path=paths.SOURCE_RUBRIC_PATH,
    )


def test_duplicate_case_id_is_reported(tmp_path):
    copies = _copy_inputs(tmp_path)
    dataset = json.loads(copies["cases"].read_text())
    dataset["cases"][1]["case_id"] = "D3-01"
    copies["cases"].write_text(json.dumps(dataset))

    problems = _validate(copies, source_cases=copies["cases"])["problems"]

    assert any("D3-01 appears 2 times" in problem for problem in problems)


def test_changed_expectation_is_detected_against_supplied_source(tmp_path):
    if not paths.SOURCE_CASES_PATH.exists():
        pytest.skip("day3_materials/ not supplied")
    copies = _copy_inputs(tmp_path)
    dataset = json.loads(copies["cases"].read_text())
    dataset["cases"][0]["prohibited_behaviour"] = ["Claim VPN is operational"]  # silently dropped one
    copies["cases"].write_text(json.dumps(dataset, indent=2))

    problems = _validate(copies)["problems"]

    assert any("differs from the supplied" in problem for problem in problems)


def test_invalid_context_status_is_reported(tmp_path):
    copies = _copy_inputs(tmp_path)
    dataset = json.loads(copies["cases"].read_text())
    dataset["cases"][0]["approved_context"]["service_status"] = "down"
    copies["cases"].write_text(json.dumps(dataset))

    problems = _validate(copies, source_cases=copies["cases"])["problems"]

    assert any("service_status" in problem for problem in problems)


def test_rubric_with_wrong_dimension_order_is_reported(tmp_path):
    copies = _copy_inputs(tmp_path)
    rubric = json.loads(copies["rubric"].read_text())
    rubric["dimension_order"] = ["safety", "correctness", "relevance", "completeness"]
    copies["rubric"].write_text(json.dumps(rubric))

    problems = _validate(copies, source_cases=copies["cases"])["problems"]

    assert any("dimension_order" in problem for problem in problems)


def test_every_case_has_exactly_one_mock_response(tmp_path):
    copies = _copy_inputs(tmp_path)
    mock = json.loads(copies["mock"].read_text())
    del mock["responses"]["D3-07"]
    copies["mock"].write_text(json.dumps(mock))

    problems = _validate(copies, source_cases=copies["cases"])["problems"]

    assert any("no MOCK response for D3-07" in problem for problem in problems)
