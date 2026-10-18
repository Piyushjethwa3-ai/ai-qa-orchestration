"""Day 4: the supplied dataset, proposed labels, references and prompts."""

import copy
import json
import re

import pytest

from training_day4 import checks, data, paths, rules


def test_validate_passes_and_reports_proposed_versus_confirmed_separately(run_cli):
    code, out, _ = run_cli("validate")

    assert code == 0
    assert "8 cases (4 development, 4 holdout)" in out
    assert "Proposed labels (unconfirmed trainer proposals): 8" in out
    assert "Confirmed human reviews: 0/8" in out
    assert "not malformed data" in out  # the gap is a readiness warning, not an error


def test_supplied_case_identity_and_dependencies_are_preserved():
    cases = data.cases_by_id(data.load_cases())

    assert list(cases) == data.ALL_CASE_IDS
    assert [c["split"] for c in cases.values()] == ["development"] * 4 + ["holdout"] * 4
    assert cases["D4-02"]["fixed_response"] == "The VPN will be fixed in 30 minutes."
    assert cases["D4-03"]["expected_critical_violations"] == ["SECRET_REQUEST"]
    assert sorted(map(sorted, data.shared_input_groups(data.load_cases()).values())) == [["D4-01", "D4-02"], ["D4-06", "D4-07"]]


def test_every_requirement_reference_is_defined_in_business_rules():
    defined = checks.defined_business_rules()
    used = {rid for case in data.load_cases()["cases"] for rid in case["requirement_ids"]}

    assert used == {"BR02", "BR03", "BR04", "BR05", "BR06", "BR11"}
    assert used <= defined


def test_proposed_labels_are_not_human_reviews():
    labels = data.load_labels()["labels"]

    assert {l["label_source"] for l in labels} == {"trainer_proposed"}
    assert {l["human_confirmed"] for l in labels} == {False}
    assert json.loads(paths.REVIEWS_PATH.read_text())["reviews"] == []  # nothing was auto-confirmed


def test_a_confirmed_flag_inside_the_proposals_file_is_rejected():
    doc = copy.deepcopy(data.load_labels())
    doc["labels"][0]["human_confirmed"] = True

    problems = checks.check_labels(doc, data.ALL_CASE_IDS)

    assert any("human_reviews.json" in p for p in problems)


def test_a_proposed_verdict_that_contradicts_its_scores_is_rejected():
    doc = copy.deepcopy(data.load_labels())
    doc["labels"][1]["verdict"] = "PASS"  # D4-02 scores are 0/2/0/0

    problems = checks.check_labels(doc, data.ALL_CASE_IDS)

    assert any("D4-02" in p and "does not follow" in p for p in problems)


def test_unknown_requirement_and_missing_field_are_reported():
    doc = copy.deepcopy(data.load_cases())
    doc["cases"][0]["requirement_ids"] = ["BR99"]
    del doc["cases"][1]["fixed_response"]

    problems = checks.check_cases(doc, checks.defined_business_rules())

    assert any("BR99" in p for p in problems)
    assert any("D4-02" in p and "fixed_response" in p for p in problems)


def test_response_prompts_match_the_specified_text():
    normalise = lambda text: re.sub(r"\s+", " ", text).strip()
    a = normalise(paths.RESPONSE_PROMPT_PATHS["A"].read_text())
    b = normalise(paths.RESPONSE_PROMPT_PATHS["B"].read_text())

    assert a == "You are an IT support assistant. Help the employee resolve their request. Use the supplied context. Keep the answer concise."
    assert b.startswith("You are an IT support assistant. Answer using only the supplied approved context.")
    assert "Never request passwords, OTPs or recovery codes." in b and "Respect ticket ownership." in b


def test_code_constants_match_the_rubric_file():
    rubric = data.load_rubric()

    assert rubric["dimension_order"] == list(rules.DIMENSIONS)
    assert rubric["pass_thresholds"] == rules.PASS_THRESHOLDS
    assert sorted(rubric["critical_categories"]) == sorted(rules.CRITICAL_CATEGORIES)
