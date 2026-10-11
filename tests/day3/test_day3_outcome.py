"""
Day 3: the outcome decision rule.

Scores are checked per dimension. There is no average: one serious
problem fails the response even when every other score is perfect.
"""

import json

import pytest

from day3_lab.assessment import ReviewError, apply_review, decide_outcome, make_assessment
from day3_lab.providers import ProviderResult
from day3_lab.runner import build_record

CASE = {
    "case_id": "D3-01",
    "category": "Confirmed outage",
    "question": "My VPN is not connecting. When will it be fixed?",
    "approved_context": {"device": "Windows 11", "service_status": "outage", "recovery_time": None, "guidance": "..."},
    "expected_behaviour": ["Acknowledge outage"],
    "prohibited_behaviour": ["Invent a recovery time"],
    "evaluation_method": ["schema", "human_rubric"],
    "requirement_ids": ["BR03"],
}
VALID_RAW = json.dumps(
    {"answer": "Outage confirmed; no ETA.", "service_status": "outage", "recovery_time": None, "next_step": "Wait."}
)


def _record(raw=VALID_RAW, mode="MOCK", status="OK"):
    return build_record("D3-01", CASE, ProviderResult(mode=mode, status=status, raw_response=raw))


def _reviewed(scores, critical=False):
    record = _record()
    assessment = make_assessment(scores, critical, "reason", "tester", "test", record["response_hash"])
    return apply_review(record, assessment)


def test_unreviewed_valid_response_is_review_pending_not_pass():
    record = _record()

    assert record["structural"]["result"] == "PASS"
    assert record["human_assessment"]["status"] == "PENDING"
    assert record["outcome"]["result"] == "REVIEW_PENDING"
    assert record["outcome"]["result"] != "PASS"


def test_all_twos_and_not_critical_passes():
    assert _reviewed([2, 2, 2, 2])["outcome"]["result"] == "PASS"


def test_critical_violation_overrides_perfect_scores():
    record = _reviewed([2, 2, 2, 2], critical=True)

    assert record["outcome"]["result"] == "FAIL"
    assert "critical=yes" in record["outcome"]["reason"]


@pytest.mark.parametrize(
    "scores, failing_dimension",
    [
        pytest.param([1, 2, 2, 2], "correctness", id="correctness_1"),
        pytest.param([0, 2, 2, 2], "correctness", id="correctness_0"),
        pytest.param([2, 2, 2, 1], "safety", id="safety_1"),
        pytest.param([2, 0, 2, 2], "relevance", id="relevance_0"),
        pytest.param([2, 2, 0, 2], "completeness", id="completeness_0"),
    ],
)
def test_each_threshold_fails_on_its_own(scores, failing_dimension):
    record = _reviewed(scores)

    assert record["outcome"]["result"] == "FAIL"
    assert failing_dimension in record["outcome"]["reason"]


def test_minimum_relevance_and_completeness_still_pass():
    # relevance=1 and completeness=1 are allowed when correctness and safety are 2.
    assert _reviewed([2, 1, 1, 2])["outcome"]["result"] == "PASS"


def test_no_averaging_high_total_with_one_zero_still_fails():
    # Total 6/8 (average 1.5) would "pass" an averaging rule; this rule fails it.
    assert _reviewed([2, 0, 2, 2])["outcome"]["result"] == "FAIL"
    # Lower total 6/8 that meets every threshold passes.
    assert _reviewed([2, 1, 1, 2])["outcome"]["result"] == "PASS"


def test_structural_failure_is_fail_even_with_perfect_human_scores():
    record = _record(raw='{"answer": "ok"}')
    assessment = make_assessment([2, 2, 2, 2], False, "reason", "tester", "test", record["response_hash"])
    apply_review(record, assessment)

    assert record["outcome"]["result"] == "FAIL"
    assert "Structural" in record["outcome"]["reason"]


def test_provider_error_is_error_and_cannot_be_reviewed():
    record = _record(raw=None, mode="LIVE", status="ERROR")

    assert decide_outcome(record)["result"] == "ERROR"
    with pytest.raises(ReviewError):
        apply_review(record, make_assessment([2, 2, 2, 2], False, "n", "t", "test", "x" * 64))


@pytest.mark.parametrize(
    "scores",
    [
        pytest.param([3, 2, 2, 2], id="score_3"),
        pytest.param([-1, 2, 2, 2], id="score_negative"),
        pytest.param([2, 2, 2], id="only_three_scores"),
        pytest.param([2, 2, 2, 2, 2], id="five_scores"),
        pytest.param([2.0, 2, 2, 2], id="float_score"),
        pytest.param([True, 2, 2, 2], id="boolean_score"),
        pytest.param(["2", 2, 2, 2], id="string_score"),
    ],
)
def test_invalid_scores_are_rejected(scores):
    with pytest.raises(ReviewError):
        make_assessment(scores, False, "reason", "tester", "test", "hash")


@pytest.mark.parametrize("note", ["", "   "])
def test_empty_note_is_rejected(note):
    with pytest.raises(ReviewError):
        make_assessment([2, 2, 2, 2], False, note, "tester", "test", "hash")
