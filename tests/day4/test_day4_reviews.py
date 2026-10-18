"""Day 4: human review commands keep proposals, judge output and human assessments apart."""

import hashlib
import json

from training_day4 import data, paths


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_review_fixed_records_a_named_human_without_touching_the_proposal(run_cli):
    proposals_before = sha(paths.LABELS_PATH)

    code, out, _ = run_cli("review-fixed", "--case", "D4-03", "--scores", "0", "2", "0", "0", "--critical", "SECRET_REQUEST",
                           "--reason", "Asks for a password and OTP.", "--reviewer", "Meera Iyer")
    review = json.loads(paths.REVIEWS_PATH.read_text())["reviews"][0]

    assert code == 0 and "verdict computed in code: FAIL" in out
    assert review["human_confirmed"] is True and review["reviewer"] == "Meera Iyer" and review["basis"] == "typed_scores"
    assert review["verdict"] == "FAIL" and review["total"] == 2 and review["critical_violations"] == ["SECRET_REQUEST"]
    assert sha(paths.LABELS_PATH) == proposals_before
    assert all(label["human_confirmed"] is False for label in data.load_labels()["labels"])


def test_review_is_bound_to_the_case_and_rubric_fingerprints(run_cli):
    run_cli("review-fixed", "--case", "D4-04", "--scores", "2", "2", "2", "2", "--critical", "NONE", "--reason", "Fine.", "--reviewer", "Meera Iyer")
    bound = json.loads(paths.REVIEWS_PATH.read_text())["reviews"][0]["bound_to"]
    case = data.cases_by_id(data.load_cases())["D4-04"]

    assert bound == data.case_binding(case, data.sha256_file(paths.RUBRIC_PATH), "day4-v1")
    assert set(bound) >= {"user_input_sha256", "approved_context_sha256", "response_sha256", "rubric_sha256", "rubric_version"}


def test_a_second_review_supersedes_but_keeps_the_first(run_cli):
    args = ("review-fixed", "--case", "D4-01", "--critical", "NONE", "--reviewer", "Meera Iyer")
    run_cli(*args, "--scores", "2", "2", "2", "2", "--reason", "First reading.")
    run_cli(*args, "--scores", "2", "2", "1", "2", "--reason", "Second reading.")
    reviews = json.loads(paths.REVIEWS_PATH.read_text())["reviews"]

    assert [r["reason"] for r in reviews] == ["First reading.", "Second reading."]
    assert reviews[1]["supersedes"] == reviews[0]["review_id"] and reviews[0]["supersedes"] is None


def test_confirming_a_proposal_is_an_explicit_named_action(run_cli):
    code, _, _ = run_cli("review-fixed", "--case", "D4-06", "--confirm-proposed", "--reason", "Paraphrase keeps every step.", "--reviewer", "Meera Iyer")
    review = json.loads(paths.REVIEWS_PATH.read_text())["reviews"][0]
    proposed = data.labels_by_id(data.load_labels())["D4-06"]

    assert code == 0 and review["basis"] == "confirmed_proposed_label" and review["scores"] == proposed["scores"]
    # without a real reviewer or a reason it is refused
    assert run_cli("review-fixed", "--case", "D4-06", "--confirm-proposed", "--reason", "ok", "--reviewer", "your name")[0] == 2
    assert run_cli("review-fixed", "--case", "D4-06", "--confirm-proposed", "--reviewer", "Meera Iyer")[0] == 2


def test_invalid_reviews_are_refused_and_nothing_is_saved(run_cli):
    base = ("review-fixed", "--case", "D4-01", "--reviewer", "Meera Iyer", "--reason", "x")
    bad = [
        (*base, "--scores", "3", "2", "2", "2", "--critical", "NONE"),
        (*base, "--scores", "2", "2", "2", "--critical", "NONE"),
        (*base, "--scores", "2", "2", "2", "2", "--critical", "MADE_UP"),
        (*base, "--scores", "2", "2", "2", "2", "--critical", "NONE", "SECRET_REQUEST"),
        ("review-fixed", "--case", "D4-01", "--scores", "2", "2", "2", "2", "--critical", "NONE", "--reason", "x", "--reviewer", "Claude"),
        ("review-fixed", "--case", "D4-01", "--scores", "2", "2", "2", "2", "--critical", "NONE", "--reason", "  ", "--reviewer", "Meera Iyer"),
        ("review-fixed", "--case", "D4-99", "--scores", "2", "2", "2", "2", "--critical", "NONE", "--reason", "x", "--reviewer", "Meera Iyer"),
        (*base, "--confirm-proposed", "--scores", "2", "2", "2", "2"),
    ]
    for command in bad:
        assert run_cli(*command)[0] == 2, command
    assert json.loads(paths.REVIEWS_PATH.read_text())["reviews"] == []


def test_generated_answer_reviews_are_separate_records_and_leave_the_run_untouched(run_cli, reports):
    run_cli("compare", "--mode", "replay", "--cases", "D4-01", "--seed", "2")
    folder = next(iter(reports()))
    run_json = paths.REPORTS_DIR / folder / "run.json"
    before = sha(run_json)
    record = json.loads(run_json.read_text())["records"][0]

    code, out, _ = run_cli("review-generated", "--run", folder, "--response", record["response_id"], "--scores", "2", "2", "2", "2",
                           "--critical", "NONE", "--reason", "Matches the context.", "--reviewer", "Meera Iyer")
    saved = json.loads((paths.REPORTS_DIR / folder / "human_reviews.json").read_text())["reviews"][0]

    assert code == 0 and sha(run_json) == before  # original evidence is unchanged
    assert saved["target"]["response_id"] == record["response_id"] and saved["bound_to"]["response_sha256"] == record["response_sha256"]
    assert saved["human_confirmed"] is True and "judge's assessment were not changed" in out
    assert "human reviews of generated answers: 1 of 2" in run_cli("summary")[1]
    assert run_cli("review-generated", "--run", folder, "--response", "R-00000000", "--scores", "2", "2", "2", "2",
                   "--critical", "NONE", "--reason", "x", "--reviewer", "Meera Iyer")[0] == 2


def test_show_case_separates_proposed_from_confirmed_and_shows_the_judge_view(run_cli):
    code, out, _ = run_cli("show-case", "--case", "D4-02")

    assert code == 0
    assert "TRAINER-PROPOSED label (NOT a human assessment; unconfirmed)" in out
    assert "CONFIRMED human review ---\nnone recorded" in out
    assert "FIXED RESPONSE: The VPN will be fixed in 30 minutes." in out
    judge_view = out.split("Exactly what the judge would receive")[1]
    assert "TRAINER-PROPOSED" not in judge_view and "D4-02" not in judge_view
    assert run_cli("show-case", "--case", "D4-99")[0] == 2
