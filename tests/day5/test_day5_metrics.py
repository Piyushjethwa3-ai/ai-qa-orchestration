"""Day 5: precision, recall, the classroom gate and aggregates (document IDs are the unit)."""

import copy

import pytest

from training_day5 import cases, metrics
from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)

OBS = ["KB-VPN-MAC-OLD", "KB-VPN-WIN-OLD"]


def score(answerable, expected, retrieved, prohibited=OBS):
    return metrics.score_case(answerable, expected, prohibited, retrieved)


def test_perfect_retrieval_passes_with_full_precision_and_recall():
    result = score(True, ["A"], ["A"])

    assert (result["precision"], result["recall"], result["result"]) == (1.0, 1.0, "PASS")


def test_extra_irrelevant_results_lower_precision_but_do_not_fail_the_gate():
    result = score(True, ["A"], ["A", "B", "C"])

    assert result["precision"] == pytest.approx(1 / 3) and result["recall"] == 1.0 and result["result"] == "PASS"
    assert "lowered precision" in result["explanation"]


def test_partial_recall_fails_and_names_the_missing_document():
    result = score(True, ["A", "B"], ["A", "C"])

    assert result["recall"] == 0.5 and result["precision"] == 0.5 and result["missing_ids"] == ["B"] and result["result"] == "FAIL"


def test_an_empty_result_for_an_answerable_case_has_zero_precision_and_recall():
    result = score(True, ["A"], [])

    assert (result["precision"], result["recall"], result["result"]) == (0.0, 0.0, "FAIL")


def test_a_prohibited_document_fails_even_with_full_recall():
    result = score(True, ["A"], ["A", "KB-VPN-MAC-OLD"])

    assert result["recall"] == 1.0 and result["prohibited_matches"] == ["KB-VPN-MAC-OLD"] and result["result"] == "FAIL"


def test_a_repeated_document_is_counted_once():
    result = score(True, ["A"], ["A", "A", "B"])

    assert result["precision"] == 0.5


def test_unanswerable_case_passes_only_with_an_empty_result_and_has_no_precision_or_recall():
    passed, failed = score(False, [], []), score(False, [], ["KB-VPN-OUTAGE"])

    assert (passed["precision"], passed["recall"], passed["result"]) == (None, None, "PASS")
    assert (failed["precision"], failed["recall"], failed["result"]) == (None, None, "FAIL")
    assert "not proof of model hallucination" in failed["explanation"]
    assert metrics.display(None) == "N/A" and metrics.display(0.5) == "0.500"


def result_row(case_id, answerable, precision, recall, result, prohibited=()):
    return {"case_id": case_id, "answerable": answerable, "precision": precision, "recall": recall, "result": result,
            "prohibited_matches": list(prohibited)}


def test_macro_metrics_average_answerable_cases_only_and_report_the_rest_separately():
    rows = [result_row("A1", True, 1.0, 1.0, "PASS"), result_row("A2", True, 0.5, 0.5, "FAIL"),
            result_row("A3", True, 0.0, 1.0, "FAIL", prohibited=["KB-X"]),
            result_row("U1", False, None, None, "PASS"), result_row("U2", False, None, None, "FAIL")]

    agg = metrics.aggregate(rows)

    assert agg["macro_precision"] == pytest.approx(0.5) and agg["macro_recall"] == pytest.approx(2.5 / 3)
    assert (agg["answerable_cases"], agg["unanswerable_cases"]) == (3, 2)
    assert (agg["unanswerable_passed"], agg["answerable_passed"]) == (1, 1)
    assert (agg["passed"], agg["failed"], agg["failed_case_ids"]) == (2, 3, ["A2", "A3", "U2"])
    assert agg["prohibited_failure_count"] == 1 and agg["prohibited_failure_cases"] == ["A3"]
    assert "classroom gate" in agg["gate_explanation"].lower()


def test_macro_metrics_are_undefined_when_there_are_no_answerable_cases():
    agg = metrics.aggregate([result_row("U1", False, None, None, "PASS")])

    assert agg["macro_precision"] is None and agg["macro_recall"] is None


# ------------------------------------------------------------------ the supplied labels

def test_supplied_labels_match_the_specification(corpus):
    doc = cases.load_cases_doc()
    by_id = {c["case_id"]: c for c in doc["cases"]}
    obsolete = {d.doc_id for d in corpus.documents if d.status == "obsolete"}

    assert list(by_id) == [f"R{i:02d}" for i in range(1, 11)]
    assert [c["answerable"] for c in by_id.values()] == [True] * 8 + [False] * 2
    assert by_id["R07"]["expected_doc_ids"] == ["KB-VPN-MAC-CURRENT", "KB-SUPPORT-ESCALATION"]
    assert by_id["R08"]["expected_doc_ids"] == ["KB-VPN-WIN-CURRENT", "KB-SUPPORT-ESCALATION"]
    assert by_id["R09"]["expected_doc_ids"] == by_id["R10"]["expected_doc_ids"] == []
    for case in doc["cases"]:
        assert obsolete <= set(case["prohibited_doc_ids"])
    assert "KB-VPN-WIN-CURRENT" in by_id["R01"]["prohibited_doc_ids"] and "KB-VPN-MAC-CURRENT" in by_id["R02"]["prohibited_doc_ids"]


def check(doc, corpus):
    return cases.inspect_cases(doc, {d.doc_id for d in corpus.documents}, {d.doc_id for d in corpus.documents if d.status == "obsolete"})


def test_the_real_dataset_is_valid(corpus):
    assert check(cases.load_cases_doc(), corpus) == []


@pytest.mark.parametrize(
    "mutate, expected_text",
    [
        pytest.param(lambda d: d["cases"][0].update(answerable=False), "answerable must be true exactly when", id="answerable_without_labels"),
        pytest.param(lambda d: d["cases"][8].update(expected_doc_ids=["KB-VPN-OUTAGE"]), "answerable must be true exactly when", id="unanswerable_with_labels"),
        pytest.param(lambda d: d["cases"][0].update(expected_doc_ids=["KB-NOPE"]), "unknown document", id="unknown_expected_id"),
        pytest.param(lambda d: d["cases"][0].update(prohibited_doc_ids=["KB-VPN-MAC-CURRENT"]), "both expected and prohibited", id="expected_and_prohibited"),
        pytest.param(lambda d: d["cases"][0].update(prohibited_doc_ids=["KB-VPN-MAC-OLD"]), "must prohibit the obsolete", id="obsolete_not_prohibited"),
        pytest.param(lambda d: d["cases"][1].update(case_id="R01"), "appears more than once", id="duplicate_case_id"),
        pytest.param(lambda d: d["cases"][0].pop("rationale"), "missing field", id="missing_field"),
        pytest.param(lambda d: d["cases"][0].update(os="plan9"), "os must be one of", id="bad_os"),
        pytest.param(lambda d: d["cases"][0].update(answerable="yes"), "answerable must be true or false", id="non_boolean_answerable"),
        pytest.param(lambda d: d["cases"][0].update(query="  "), "query must be non-empty", id="blank_query"),
    ],
)
def test_invalid_cases_are_reported(corpus, mutate, expected_text):
    doc = copy.deepcopy(cases.load_cases_doc())
    mutate(doc)

    problems = check(doc, corpus)

    assert any(expected_text in p for p in problems), problems
