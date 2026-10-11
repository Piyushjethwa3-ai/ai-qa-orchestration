"""
Day 3: the controlled failure clinic.

These tests check that the clinic EVIDENCE is right: the bad fixtures are
structurally valid (so schema checks cannot catch them), nothing is
labelled automatically, the exact-string check is shown separately and
never decides the outcome, and the corrected run never alters the
original run.

They deliberately do NOT assert that the paraphrase is semantically
correct. Only a human review can decide that.
"""

import pytest


@pytest.fixture()
def clinic(tmp_path, run_cli, read_json):
    code, _, _ = run_cli("clinic", "--out", tmp_path / "clinic")
    assert code == 0
    run = read_json(tmp_path / "clinic" / "run.json")
    return tmp_path / "clinic", {record["record_id"]: record for record in run["records"]}


def test_clinic_saves_json_html_and_notes(clinic):
    out, records = clinic

    assert {"run.json", "run.html", "clinic_notes.md"} <= {p.name for p in out.iterdir()}
    assert set(records) == {"D3-01-fluent-wrong", "D3-04-unsafe", "D3-01-paraphrase"}
    assert {r["source"] for r in records.values()} == {"MOCK"}


def test_no_fixture_label_is_recorded_as_a_human_review(clinic):
    _, records = clinic

    for record in records.values():
        assert record["human_assessment"] == {"status": "PENDING", "current": None, "history": []}
        assert record["outcome"]["result"] == "REVIEW_PENDING"
        assert "not a recorded human review" in record["clinic"]["teaching_expectation_status"].lower()


def test_fluent_wrong_answer_passes_schema_with_fabricated_eta(clinic):
    record = clinic[1]["D3-01-fluent-wrong"]
    parsed = record["parsed_response"]

    assert record["structural"]["result"] == "PASS"
    assert record["case"]["approved_context"]["recovery_time"] is None
    assert parsed["service_status"] == "outage"
    assert parsed["recovery_time"] == "30 minutes"
    assert "30 minutes" in parsed["answer"]


def test_unsafe_answer_passes_schema_while_requesting_secrets(clinic):
    record = clinic[1]["D3-04-unsafe"]
    text = (record["parsed_response"]["answer"] + " " + record["parsed_response"]["next_step"]).lower()

    assert record["structural"]["result"] == "PASS"
    assert "password" in text and "otp" in text
    assert record["clinic"]["teaching_expectation"]["critical"] == "yes"


def test_paraphrase_is_not_rejected_by_the_exact_output_assertion(clinic):
    record = clinic[1]["D3-01-paraphrase"]
    check = record["exact_string_check"]

    # The naive evaluator says FAIL...
    assert check["result"] == "FAIL"
    assert check["actual"] != check["reference"]
    assert "NOT the quality verdict" in check["status"]
    # ...but it does not decide the outcome: structure passes and a human must review.
    assert record["structural"]["result"] == "PASS"
    assert record["outcome"]["result"] == "REVIEW_PENDING"
    assert record["parsed_response"]["recovery_time"] is None


def test_corrected_variant_preserves_original_clinic_evidence(tmp_path, run_cli, read_json):
    original = tmp_path / "clinic"
    run_cli("clinic", "--out", original)
    snapshot = {p.name: p.read_bytes() for p in original.iterdir()}

    code, _, _ = run_cli("clinic", "--variant", "corrected", "--out", tmp_path / "clinic-fixed")
    refused, _, _ = run_cli("clinic", "--variant", "corrected", "--out", original)

    assert code == 0
    assert refused == 2  # cannot write the corrected set over the originals
    assert {p.name: p.read_bytes() for p in original.iterdir()} == snapshot


def test_corrected_variant_is_labelled_mock_correction_and_unreviewed(tmp_path, run_cli, read_json):
    run_cli("clinic", "--out", tmp_path / "clinic")
    run_cli("clinic", "--variant", "corrected", "--out", tmp_path / "clinic-fixed")
    original = {r["record_id"]: r for r in read_json(tmp_path / "clinic" / "run.json")["records"]}
    fixed_run = read_json(tmp_path / "clinic-fixed" / "run.json")
    fixed = {r["record_id"]: r for r in fixed_run["records"]}

    assert "NOT proof that a live prompt improved" in fixed_run["disclaimer"]
    assert fixed["D3-01-fluent-wrong-corrected"]["clinic"]["corrects"] == "D3-01-fluent-wrong"
    assert fixed["D3-01-fluent-wrong-corrected"]["parsed_response"]["recovery_time"] is None
    assert "30 minutes" not in fixed["D3-01-fluent-wrong-corrected"]["raw_response"]
    assert "CORRECTION" in fixed["D3-04-unsafe-corrected"]["clinic"]["label"]
    for record in fixed.values():
        assert record["source"] == "MOCK"
        assert record["structural"]["result"] == "PASS"
        assert record["outcome"]["result"] == "REVIEW_PENDING"
    # The paraphrase is unchanged, so it has the same response hash in both runs.
    assert fixed["D3-01-paraphrase"]["response_hash"] == original["D3-01-paraphrase"]["response_hash"]


def test_clinic_review_is_saved_only_when_explicitly_entered(clinic, run_cli, read_json):
    out, _ = clinic

    code, _, _ = run_cli("review", "--report", out / "run.json", "--case", "D3-04-unsafe",
                         "--scores", "0", "2", "0", "0", "--critical", "yes",
                         "--note", "Requests password and OTP, violating BR05.")
    records = {r["record_id"]: r for r in read_json(out / "run.json")["records"]}

    assert code == 0
    assert records["D3-04-unsafe"]["outcome"]["result"] == "FAIL"
    assert records["D3-01-fluent-wrong"]["human_assessment"]["status"] == "PENDING"
    assert records["D3-01-paraphrase"]["human_assessment"]["status"] == "PENDING"
