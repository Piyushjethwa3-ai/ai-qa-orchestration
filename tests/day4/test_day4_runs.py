"""Day 4: replay runs, immutable evidence, latest-fixed, calibration and the summary."""

import copy
import json
import re

import pytest

from training_day4 import data, execute, paths, runstore
from training_day4.execute import Context


def make_judge_run(run_cli):
    code, out, _ = run_cli("judge", "--mode", "replay", "--cases", "all")
    assert code == 0
    return out


def edit_run(folder, **changes):
    path = paths.REPORTS_DIR / folder / "run.json"
    run = json.loads(path.read_text())
    run.update(changes)
    path.write_text(json.dumps(run))


# ------------------------------------------------------------------ replay

def test_replay_judge_needs_no_credentials_and_reports_no_measurements(run_cli, reports):
    code, out, _ = run_cli("judge", "--mode", "replay", "--cases", "all")
    run = next(iter(reports().values()))

    assert code == 0 and "API calls 0" in out and "Observations" not in out
    assert run["mode"] == "replay" and run["label"].startswith("REPLAY")
    assert run["call_counts"]["judge"]["calls_made"] == 0 and run["call_counts"]["judge"]["replayed_items"] == 8
    for record in run["records"]:
        assert record["judge_call"]["latency_ms"] is None and record["judge_call"]["usage"] == "unavailable"
        assert record["judge_assessment"]["source"] == "REPLAY" and record["judge_assessment"]["judge_model"] is None


def test_replay_compare_and_repeat_counts_and_retained_results(run_cli, reports):
    run_cli("compare", "--mode", "replay", "--cases", "all", "--seed", "1")
    run_cli("repeat", "--mode", "replay", "--prompt", "B", "--cases", "D4-01", "D4-06", "D4-08", "--runs", "3")
    runs = {r["kind"]: r for r in reports().values()}

    compare, repeat = runs["compare"], runs["repeat"]
    assert compare["call_counts"]["generation"]["planned"] == 16 and compare["call_counts"]["judge"]["planned"] == 16
    assert {c["split"] for c in compare["records"]} == {"development", "holdout"}
    assert len(repeat["records"]) == 9 and repeat["call_counts"]["generation"]["planned"] == 9
    assert sum(1 for r in repeat["records"] if r["judge_assessment"]["verdict"] == "FAIL") == 1  # the scripted FAIL is kept
    assert "does not isolate" in " ".join(repeat["limitations"]) and "cannot measure consistency" in " ".join(repeat["limitations"])


def test_replay_does_not_force_prompt_b_to_win(run_cli, reports):
    run_cli("compare", "--mode", "replay", "--cases", "all", "--seed", "1")
    run = next(iter(reports().values()))
    reading = execute.compare_assessment(run)
    b_fail_cases = [r["case_id"] for r in run["records"] if r["prompt"] == "B" and r["judge_assessment"]["verdict"] == "FAIL"]
    a_pass_cases = [r["case_id"] for r in run["records"] if r["prompt"] == "A" and r["judge_assessment"]["verdict"] == "PASS"]

    assert b_fail_cases and set(b_fail_cases) <= set(a_pass_cases)  # a case where A passes and B fails exists
    assert reading["preference"] == "inconclusive" and "Replay" in reading["text"]


def test_repeat_replay_supports_prompt_a_and_refuses_unknown_cases(run_cli):
    assert run_cli("repeat", "--mode", "replay", "--prompt", "A", "--cases", "D4-01", "--runs", "3")[0] == 0
    code, _, err = run_cli("judge", "--mode", "replay", "--cases", "D4-99")
    assert code == 2 and "Unknown case" in err


# ------------------------------------------------------------------ immutability

def test_each_run_gets_a_new_folder_and_existing_evidence_cannot_be_overwritten(run_cli, reports):
    make_judge_run(run_cli)
    make_judge_run(run_cli)
    folders = sorted(reports())
    before = {f: (paths.REPORTS_DIR / f / "run.json").read_bytes() for f in folders}

    assert len(folders) == 2 and folders[0] != folders[1]
    run = json.loads(before[folders[0]])
    with pytest.raises(FileExistsError):
        runstore.begin_run(run)  # same run_id: the folder already exists
    with pytest.raises(runstore.RunStoreError):
        runstore.finish_run(paths.REPORTS_DIR / folders[0], run, "x")  # already finalised
    assert {f: (paths.REPORTS_DIR / f / "run.json").read_bytes() for f in folders} == before


# ------------------------------------------------------------------ latest-fixed

def test_latest_fixed_with_no_judge_run_is_refused(run_cli):
    code, _, err = run_cli("calibrate", "--run", "latest-fixed")

    assert code == 2 and "No fixed-response judge run exists" in err


def test_latest_fixed_prints_run_id_and_mode_and_ignores_other_kinds(run_cli, reports):
    make_judge_run(run_cli)
    run_cli("compare", "--mode", "replay", "--cases", "D4-01", "--seed", "1")  # newer, but not a judge run
    judge_id = next(k for k, v in reports().items() if v["kind"] == "judge")
    code, out, _ = run_cli("calibrate", "--run", "latest-fixed")

    assert code == 0 and f"Calibrating judge run {judge_id} (mode REPLAY" in out
    calibration = next(v for v in reports().values() if v["kind"] == "calibrate")
    assert calibration["source_judge_run"]["run_id"] == judge_id and calibration["finalised"] is True


def test_latest_fixed_never_replaces_a_newer_unfinished_run_with_an_older_one(run_cli):
    make_judge_run(run_cli)
    newer = execute.base_run(Context("replay"), "judge", {"subject": "fixed_responses"})
    newer["created_at"] = "2099-01-01T00:00:00Z"
    runstore.begin_run(newer)  # begun but never finished

    code, _, err = run_cli("calibrate", "--run", "latest-fixed")

    assert code == 2 and "unfinished" in err and newer["run_id"] in err


def test_latest_fixed_rejects_corrupted_metadata(run_cli):
    make_judge_run(run_cli)
    broken = paths.REPORTS_DIR / "judge-replay-broken"
    broken.mkdir()
    (broken / "run.json").write_text("{not json")

    code, _, err = run_cli("calibrate", "--run", "latest-fixed")

    assert code == 2 and "corrupted" in err and "judge-replay-broken" in err


def test_latest_fixed_rejects_ambiguous_newest_runs(run_cli, reports):
    make_judge_run(run_cli)
    make_judge_run(run_cli)
    for folder in reports():
        edit_run(folder, created_at="2030-05-05T10:00:00Z")

    code, _, err = run_cli("calibrate", "--run", "latest-fixed")

    assert code == 2 and "Ambiguous" in err


def test_calibrating_a_non_judge_run_is_refused(run_cli, reports):
    run_cli("compare", "--mode", "replay", "--cases", "D4-01", "--seed", "1")
    folder = next(iter(reports()))

    code, _, err = run_cli("calibrate", "--run", folder)

    assert code == 2 and "not a fixed-response judge run" in err


# ------------------------------------------------------------------ calibration

def calibrate(run_cli, reports):
    code, out, _ = run_cli("calibrate", "--run", "latest-fixed")
    assert code == 0
    return out, next(v for v in reports().values() if v["kind"] == "calibrate")


def review_args(case, scores, critical="NONE", reviewer="Dr. Rao", reason="Checked against the context."):
    return ("review-fixed", "--case", case, "--scores", *map(str, scores), "--critical", critical, "--reason", reason, "--reviewer", reviewer)


def test_zero_confirmed_labels_gives_no_agreement_figure(run_cli, reports):
    make_judge_run(run_cli)
    out, run = calibrate(run_cli, reports)
    report = (paths.REPORTS_DIR / run["run_id"] / "report.md").read_text()

    assert "Confirmed human agreement: unavailable" in out
    assert run["human_calibration"]["available"] is False
    assert run["coverage"]["confirmed_human_reviews"] == 0 and "0/8" in report
    assert "unavailable" in report and "0%" not in report and "100%" not in report
    assert "PROVISIONAL" in report
    lowered = report.lower()
    for match in re.finditer("is reliable", lowered):
        assert re.search(r"(do not show|cannot establish) that a judge $", lowered[: match.start()]), "'reliable' must only appear negated"
    assert run["provisional_proposed_label_comparison"]["all_cases"]["valid_pairs"] == 8
    assert all(r["confirmed_human_assessment"]["status"] == "NONE" for r in run["rows"])


def test_replay_calibration_is_labelled_a_workflow_demonstration(run_cli, reports):
    make_judge_run(run_cli)
    _, run = calibrate(run_cli, reports)

    assert "workflow demonstration" in " ".join(run["limitations"])
    assert run["source_evidence_mode"] == "replay" and run["mode"] == "offline"
    assert run["coverage"]["gap_to_week2_target"] == 15


def test_confirmed_reviews_drive_the_human_agreement_counts_and_denominators(run_cli, reports):
    make_judge_run(run_cli)
    # The replay judge says D4-01 PASS (8/8) and D4-02 FAIL. Review D4-01 as a FAIL (false pass) and D4-02 as a FAIL (agree).
    assert run_cli(*review_args("D4-01", (0, 2, 0, 0), "UNSAFE_SECURITY_ADVICE"))[0] == 0
    assert run_cli(*review_args("D4-02", (0, 2, 0, 0)))[0] == 0
    _, run = calibrate(run_cli, reports)
    overall = run["human_calibration"]["all_cases"]

    assert run["human_calibration"]["available"] is True
    assert overall["valid_pairs"] == 2 and overall["verdict_agreements"] == 1
    assert overall["false_passes"] == ["D4-01"] and overall["false_fails"] == []
    assert [c["case_id"] for c in overall["critical_disagreements"]] == ["D4-01"]
    assert run["human_calibration"]["development"]["valid_pairs"] == 2 and run["human_calibration"]["holdout"]["valid_pairs"] == 0
    assert run["coverage"]["confirmed_human_reviews"] == 2 and run["coverage"]["cases_without_confirmed_review"] == 6


def test_missing_evaluations_are_explicit_and_excluded_from_pairs(run_cli, reports):
    run_cli("judge", "--mode", "replay", "--cases", "D4-01", "D4-02")  # only two of eight cases judged
    run_cli(*review_args("D4-05", (0, 2, 0, 0), "UNVERIFIED_ACTION_CLAIM"))  # reviewed, but never judged
    _, run = calibrate(run_cli, reports)

    assert run["coverage"]["cases_without_valid_judge_evaluation"] == 6
    assert run["provisional_proposed_label_comparison"]["all_cases"]["valid_pairs"] == 2
    row = next(r for r in run["rows"] if r["case_id"] == "D4-05")
    assert row["judge_assessment"]["status"] == "MISSING" and row["execution_error"]["category"] == "no_judge_record"
    assert run["human_calibration"]["available"] is False  # the only review has no judge evaluation to pair with


def test_a_review_goes_stale_when_the_case_or_rubric_changes(run_cli, reports, monkeypatch, tmp_path):
    make_judge_run(run_cli)
    run_cli(*review_args("D4-02", (0, 2, 0, 0)))

    original_cases, original_rubric = paths.CASES_PATH, paths.RUBRIC_PATH
    changed_cases = copy.deepcopy(data.load_cases())
    changed_cases["cases"][1]["fixed_response"] = "The VPN will be fixed in 31 minutes."
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(changed_cases))
    monkeypatch.setattr(paths, "CASES_PATH", cases_path)
    out, run = calibrate(run_cli, reports)
    row = next(r for r in run["rows"] if r["case_id"] == "D4-02")

    assert row["confirmed_human_assessment"]["status"] == "STALE" and "response_sha256" in row["confirmed_human_assessment"]["detail"]
    assert run["human_calibration"]["available"] is False and run["coverage"]["stale_human_reviews"] == 1
    assert "dataset_cases_sha256" in run["version_drift"]["differs_from_current_files"]
    validate_out = run_cli("validate")[1]
    assert "stale: 1" in validate_out and "Stale human reviews" in validate_out and "D4-02" in validate_out

    monkeypatch.setattr(paths, "CASES_PATH", original_cases)  # restore the case; now change the rubric instead
    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(json.dumps(data.load_rubric(), indent=4))  # same content, different bytes -> different hash
    monkeypatch.setattr(paths, "RUBRIC_PATH", rubric_path)
    assert "stale: 1" in run_cli("validate")[1]
    monkeypatch.setattr(paths, "RUBRIC_PATH", original_rubric)
    assert "stale: 0" in run_cli("validate")[1]  # unchanged inputs: the review is current again


# ------------------------------------------------------------------ summary

def test_summary_before_anything_has_run(run_cli):
    code, out, _ = run_cli("summary")

    assert code == 0 and out.count("NOT RUN") == 9
    assert "confirmed: 0/8" in out and "NOT COMPLETE" in out


def test_summary_separates_modes_and_states_and_never_marks_review_complete(run_cli):
    make_judge_run(run_cli)
    run_cli("compare", "--mode", "replay", "--cases", "all", "--seed", "1")
    newer = execute.base_run(Context("replay"), "repeat", {"prompt": "B", "case_ids": [], "runs_per_case": 3})
    runstore.begin_run(newer)  # an interrupted run
    code, out, _ = run_cli("summary")

    lines = {(l.split()[0], l.split()[1]): l for l in out.splitlines() if l[:1].isalpha() and len(l.split()) >= 3 and l.split()[1] in ("live", "replay")}
    assert "COMPLETED" in lines[("judge", "replay")] and "NOT RUN" in lines[("judge", "live")]
    assert "UNFINISHED" in lines[("repeat", "replay")] and "NOT RUN" in lines[("repeat", "live")]
    assert "human reviews of generated answers: 0 of 16" in out and "NOT COMPLETE" in out
    assert "Replay rows are teaching fixtures" in out


def test_compare_with_critical_failures_in_both_prompts_recommends_neither():
    def record(prompt, critical):
        return {"prompt": prompt, "response_id": f"R-{prompt}{len(critical)}", "judge_assessment": {
            "status": "EVALUATED", "verdict": "FAIL" if critical else "PASS", "critical_violations": critical}}

    run = {"mode": "live", "records": [record("A", ["SECRET_REQUEST"]), record("B", ["UNSAFE_SECURITY_ADVICE"])]}

    reading = execute.compare_assessment(run)

    assert reading["preference"] == "none" and "Neither prompt" in reading["text"]


def test_a_provisional_preference_needs_every_answer_reviewed_by_a_human():
    def record(prompt):
        return {"prompt": prompt, "response_id": f"R-{prompt}", "judge_assessment": {"status": "EVALUATED", "verdict": "PASS", "critical_violations": []}}

    run = {"mode": "live", "records": [record("A"), record("B")]}
    assert execute.compare_assessment(run)["preference"] == "inconclusive"
    reviews = {"R-A": {"verdict": "FAIL", "critical_violations": []}, "R-B": {"verdict": "PASS", "critical_violations": []}}
    reading = execute.compare_assessment(run, reviews)

    assert reading["preference"] == "provisional_B" and "not an approval" in reading["text"]


# ------------------------------------------------------------------ calibration is an offline comparison

ALL_CRITICAL_NONE = ("--critical", "NONE")


def record_reviews_for_all_cases(run_cli):
    for case in data.ALL_CASE_IDS:
        code, _, _ = run_cli("review-fixed", "--case", case, "--confirm-proposed",
                             "--reason", "Test review.", "--reviewer", "Dr. Rao")
        assert code == 0


def test_calibrating_live_evidence_is_labelled_as_an_offline_comparison_of_live_evidence(run_cli, make_live, reports):
    live = make_live()
    assert run_cli("judge", "--mode", "live", "--cases", "all", env=live.env, client=live.client)[0] == 0
    source_id = next(iter(reports()))
    record_reviews_for_all_cases(run_cli)
    requests_before = len(live.sdk.requests)
    source_bytes = (paths.REPORTS_DIR / source_id / "run.json").read_bytes()
    reviews_bytes = paths.REVIEWS_PATH.read_bytes()

    code, out, _ = run_cli("calibrate", "--run", source_id)  # explicit source run
    calibration = next(v for v in reports().values() if v["kind"] == "calibrate")
    report = (paths.REPORTS_DIR / calibration["run_id"] / "report.md").read_text()

    assert code == 0
    # An unambiguous run ID: it names the calibration as offline and the source mode, not "replay".
    assert calibration["run_id"].startswith("calibrate-offline-from-live-") and "replay" not in calibration["run_id"]
    # Source, source mode and execution are separate, explicit fields.
    assert calibration["source_judge_run"]["run_id"] == source_id and calibration["source_judge_run"]["mode"] == "live"
    assert calibration["source_evidence_mode"] == "live" and calibration["mode"] == "offline"
    assert "offline comparison" in calibration["execution"] and "no model calls" in calibration["execution"]
    # No replay residue anywhere: not in the hashes, the report, the on-screen summary or the run ID.
    assert "replay_fixtures_sha256" not in calibration["hashes"]
    allowed = ("no replay fixtures", "not itself live or replay evidence")  # explicit negations, not residue
    for text in (report, out):
        remainder = text.lower()
        for phrase in allowed:
            remainder = remainder.replace(phrase, "")
        assert "replay" not in remainder
    assert "Source evidence mode | LIVE" in report and "Calibration execution | offline comparison" in report
    assert f"Source judge run: {source_id}   Source evidence mode: LIVE" in out
    assert "Calibration execution: offline comparison" in out
    # The comparison itself is offline and changes nothing.
    assert len(live.sdk.requests) == requests_before
    assert (paths.REPORTS_DIR / source_id / "run.json").read_bytes() == source_bytes
    assert paths.REVIEWS_PATH.read_bytes() == reviews_bytes
    assert calibration["coverage"]["confirmed_human_reviews"] == 8 and calibration["tally"]["valid_judge_evaluations"] == 8


def test_calibrating_replay_evidence_is_also_an_offline_comparison_not_a_replay_run(run_cli, reports):
    assert run_cli("judge", "--mode", "replay", "--cases", "all")[0] == 0
    source_id = next(iter(reports()))
    run_cli("calibrate", "--run", "latest-fixed")
    calibration = next(v for v in reports().values() if v["kind"] == "calibrate")

    assert calibration["run_id"].startswith("calibrate-offline-from-replay-")
    assert calibration["mode"] == "offline" and calibration["source_evidence_mode"] == "replay"
    assert "replay_fixtures_sha256" not in calibration["hashes"]  # this step did not read the fixtures
    assert "replay_fixtures_sha256" in calibration["source_judge_run"]["hashes"]  # the source run did
    assert "Replay: no model was called" not in (paths.REPORTS_DIR / calibration["run_id"] / "report.md").read_text()


def test_summary_files_a_calibration_under_the_mode_of_its_source_evidence(run_cli, make_live):
    from training_day4 import summary

    live = make_live()
    run_cli("judge", "--mode", "live", "--cases", "all", env=live.env, client=live.client)
    run_cli("calibrate", "--run", "latest-fixed")
    out = run_cli("summary")[1]
    rows = {tuple(l.split()[:2]): l for l in out.splitlines() if l.startswith(("calibrate", "judge"))}

    assert "COMPLETED" in rows[("calibrate", "live")] and "NOT RUN" in rows[("calibrate", "replay")]
    # Calibrations saved before the change put the source mode in `mode`; they are still grouped correctly.
    assert summary.evidence_mode({"kind": "calibrate", "mode": "live"}) == "live"
    assert summary.evidence_mode({"kind": "calibrate", "mode": "offline", "source_evidence_mode": "replay"}) == "replay"
    assert summary.evidence_mode({"kind": "judge", "mode": "live"}) == "live"
