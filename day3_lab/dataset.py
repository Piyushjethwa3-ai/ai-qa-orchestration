"""
Loading and checking the Day 3 inputs: cases, rubric and fixtures.

A "JSON case" is one entry in datasets/day3/cases.json. After json.load
it becomes a Python dictionary such as:

    {"case_id": "D3-01", "question": "...", "approved_context": {...}, ...}

validate_data() loops over every case and collects problems in a list
instead of stopping at the first one, so you can fix them all at once.
"""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import jsonschema

from day3_lab import paths
from day3_lab.validation import check_structure, load_response_schema

# The order of --scores on the review command. It must match the rubric.
DIMENSIONS = ("correctness", "relevance", "completeness", "safety")
SCORE_KEYS = ("0", "1", "2")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cases(path: Path = paths.CASES_PATH) -> dict:
    return load_json(path)


def load_rubric(path: Path = paths.RUBRIC_PATH) -> dict:
    return load_json(path)


def cases_by_id(dataset: dict) -> dict[str, dict]:
    return {case["case_id"]: case for case in dataset["cases"]}


def _check_rubric(rubric: dict) -> list[str]:
    problems = []
    if not isinstance(rubric.get("version"), str) or not rubric["version"].strip():
        problems.append("rubric: 'version' must be a non-empty string.")
    if rubric.get("dimension_order") != list(DIMENSIONS):
        problems.append(
            f"rubric: dimension_order must be {list(DIMENSIONS)} to match the review "
            f"command's --scores order, found {rubric.get('dimension_order')!r}."
        )
    scales = rubric.get("scales")
    if not isinstance(scales, dict):
        problems.append("rubric: 'scales' must be an object.")
        scales = {}
    for dimension in DIMENSIONS:
        scale = scales.get(dimension)
        if not isinstance(scale, dict) or sorted(scale) != list(SCORE_KEYS):
            problems.append(f"rubric: scale for {dimension!r} must define exactly the scores 0, 1 and 2.")
            continue
        for score, description in scale.items():
            if not isinstance(description, str) or not description.strip():
                problems.append(f"rubric: {dimension} score {score} needs a description.")
    if not isinstance(rubric.get("decision_rule"), str) or not rubric["decision_rule"].strip():
        problems.append("rubric: 'decision_rule' must be a non-empty string.")
    return problems


def _defined_business_rules() -> set[str]:
    if not paths.BUSINESS_RULES_PATH.exists():
        return set()
    text = paths.BUSINESS_RULES_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"^## (BR\d{2})\b", text, flags=re.MULTILINE))


def _compare_with_source(copy_path: Path, source_path: Path, label: str, problems: list, notes: list) -> None:
    if not source_path.exists():
        notes.append(f"{label}: supplied source {paths.display_path(source_path)} not present; copy not compared.")
    elif copy_path.read_bytes() == source_path.read_bytes():
        notes.append(f"{label}: identical to supplied {paths.display_path(source_path)}.")
    else:
        problems.append(
            f"{label}: {paths.display_path(copy_path)} differs from the supplied "
            f"{paths.display_path(source_path)}. Expectations must not change silently."
        )


def validate_data(
    cases_path: Path = paths.CASES_PATH,
    rubric_path: Path = paths.RUBRIC_PATH,
    mock_path: Path = paths.MOCK_RESPONSES_PATH,
    clinic_path: Path = paths.CLINIC_FIXTURES_PATH,
    source_cases_path: Path = paths.SOURCE_CASES_PATH,
    source_rubric_path: Path = paths.SOURCE_RUBRIC_PATH,
) -> dict:
    """Check every Day 3 input. Returns a summary dict with 'problems' (failures),
    'warnings' (worth a human look, not failures) and 'notes'."""
    problems: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    for path in (cases_path, rubric_path, mock_path, clinic_path):
        if not path.exists():
            problems.append(f"Missing input file: {paths.display_path(path)}")
    if problems:
        return {"problems": problems, "warnings": warnings, "notes": notes, "case_count": 0}

    dataset = load_json(cases_path)
    rubric = load_json(rubric_path)

    # 1. Shape of the dataset, using a JSON Schema (same idea as Day 2).
    validator = jsonschema.Draft7Validator(load_json(paths.CASES_SCHEMA_PATH))
    for error in validator.iter_errors(dataset):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        problems.append(f"cases.json {location}: {error.message}")
    if problems:
        return {"problems": problems, "warnings": warnings, "notes": notes, "case_count": 0}

    # 2. Unique case IDs (JSON Schema cannot check this across items).
    case_ids = [case["case_id"] for case in dataset["cases"]]
    for case_id, count in Counter(case_ids).items():
        if count > 1:
            problems.append(f"cases.json: case_id {case_id} appears {count} times; IDs must be unique.")

    # 3. Rubric, and that cases asking for human review can use it.
    problems.extend(_check_rubric(rubric))
    if dataset["dataset_version"] != rubric.get("version"):
        problems.append(
            f"dataset_version {dataset['dataset_version']!r} does not match rubric version "
            f"{rubric.get('version')!r}."
        )
    # Every case's context status must be a value the response contract allows.
    # (cases.schema enforces the same enum; this keeps the two contracts tied together.)
    allowed = load_response_schema()["properties"]["service_status"]["enum"]
    for case in dataset["cases"]:
        if "human_rubric" not in case["evaluation_method"]:
            warnings.append(f"{case['case_id']}: no human_rubric evaluation; only structure would be checked.")
        if case["approved_context"]["service_status"] not in allowed:
            problems.append(f"{case['case_id']}: context service_status is not allowed by the response schema.")

    # 4. Requirement IDs compared with this repository's docs/business_rules.md.
    defined = _defined_business_rules()
    used = sorted({rid for case in dataset["cases"] for rid in case["requirement_ids"]})
    undefined = [rid for rid in used if rid not in defined]
    if undefined:
        warnings.append(
            f"requirement_ids {undefined} are not defined in docs/business_rules.md "
            f"(it defines {sorted(defined)}). IDs that are defined there may also mean something "
            "else (there, BR03 is 'a missing ticket returns 404'). The supplied dataset was left "
            "unchanged; confirm the course requirement catalogue with the trainer."
        )

    # 5. Mock fixtures: exactly one response per case, each structurally valid.
    mock = load_json(mock_path)
    mock_ids = set(mock.get("responses", {}))
    for missing in sorted(set(case_ids) - mock_ids):
        problems.append(f"mock_responses.json: no MOCK response for {missing}.")
    for extra in sorted(mock_ids - set(case_ids)):
        problems.append(f"mock_responses.json: response {extra} has no matching case.")
    for case_id, response in mock.get("responses", {}).items():
        _, structural = check_structure(json.dumps(response))
        if structural["result"] != "PASS":
            problems.append(f"mock_responses.json {case_id}: fixture fails the response schema.")

    # 6. Clinic fixtures: known cases, unique IDs per variant, well-formed responses.
    clinic = load_json(clinic_path)
    for variant, fixtures in clinic.get("variants", {}).items():
        fixture_ids = [fixture["fixture_id"] for fixture in fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            problems.append(f"clinic_fixtures.json {variant}: fixture IDs must be unique.")
        for fixture in fixtures:
            if fixture["case_id"] not in case_ids:
                problems.append(f"clinic {fixture['fixture_id']}: unknown case_id {fixture['case_id']}.")
            _, structural = check_structure(json.dumps(fixture["response"]))
            if structural["result"] != "PASS":
                problems.append(f"clinic {fixture['fixture_id']}: fixture fails the response schema.")

    # 7. The copies the lab reads are byte-identical to the supplied sources.
    _compare_with_source(cases_path, source_cases_path, "cases", problems, notes)
    _compare_with_source(rubric_path, source_rubric_path, "rubric", problems, notes)

    return {
        "problems": problems,
        "warnings": warnings,
        "notes": notes,
        "case_count": len(case_ids),
        "dataset_version": dataset["dataset_version"],
        "rubric_version": rubric.get("version"),
    }
