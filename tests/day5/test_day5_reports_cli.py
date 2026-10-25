"""Day 5: saved reports, exit codes, no overwriting, summary, and the real-data smoke run."""

import json

import pytest

from training_day5 import paths, report
from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)


@pytest.fixture()
def passing_dataset(tmp_path, monkeypatch):
    """A tiny test-owned dataset whose single case is expected to pass: it keeps exit-code tests
    independent of how well the real lexical baseline does on the supplied cases."""
    doc = {"dataset_version": "test-v1", "cases": [
        {"case_id": "R01", "query": "account password reset", "os": "any", "answerable": True,
         "expected_doc_ids": ["KB-ACCOUNT-RESET"], "prohibited_doc_ids": ["KB-VPN-MAC-OLD", "KB-VPN-WIN-OLD"],
         "expected_behaviour": "Retrieve the account reset document.", "rationale": "Test fixture."}]}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(paths, "CASES_PATH", path)
    return path


# ------------------------------------------------------------------ exit codes and saving

def test_all_selected_cases_passing_exits_zero_and_saves_a_report(run_cli, passing_dataset, reports_dir):
    code, out, _ = run_cli("evaluate", "--cases", "all", "--top-k", "3")
    run = next(iter(reports_dir().values()))

    assert code == 0 and "Cases passed 1 of 1" in out
    assert (paths.REPORTS_DIR / run["run_id"] / "results.json").exists() and (paths.REPORTS_DIR / run["run_id"] / "report.md").exists()
    printed = [line for line in out.splitlines() if line.startswith("Report: ")]
    assert len(printed) == 2 and all(run["run_id"] in line for line in printed)  # exact report paths are printed
    assert printed[0].endswith("results.json") and printed[1].endswith("report.md")


def test_a_completed_evaluation_with_failures_exits_one_and_is_still_saved(run_cli, reports_dir):
    code, out, _ = run_cli("evaluate", "--cases", "R01", "--top-k", "3", "--fault", "wrong-os")
    run = next(iter(reports_dir().values()))
    markdown = (paths.REPORTS_DIR / run["run_id"] / "report.md").read_text()

    assert code == 1 and "Cases passed 0 of 1" in out
    assert run["aggregates"]["failed_case_ids"] == ["R01"] and run["results"][0]["result"] == "FAIL"
    assert "Failed: " in run["results"][0]["explanation"]
    assert "R01" in markdown and "FAIL" in markdown


@pytest.mark.parametrize(
    "args",
    [
        ("evaluate", "--cases", "R99"),
        ("evaluate", "--cases", "R01", "R01"),
        ("evaluate", "--cases", "R01", "--top-k", "0"),
        ("evaluate", "--cases", "R01", "--top-k", "-2"),
        ("evaluate", "--cases", "R01", "--fault", "make-it-worse"),
        ("show-doc", "--id", "KB-NOPE"),
        ("show-case", "--id", "R99"),
        ("summary", "--run", "no-such-run"),
    ],
)
def test_invalid_input_exits_two_and_saves_nothing(run_cli, reports_dir, args):
    code, _, _ = run_cli(*args)

    assert code == 2
    assert reports_dir() == {}


def test_every_required_field_is_recorded(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01", "R09", "--top-k", "3")
    run = next(iter(reports_dir().values()))

    assert run["mode"] == "LOCAL_DETERMINISTIC" and run["top_k"] == 3 and run["created_at"].endswith("Z")
    assert run["fault"]["mode"] == "none" and run["fault"]["status"] == "NONE"
    assert set(run["git"]) == {"commit", "dirty"}
    assert {"knowledge_base_sha256", "manifest_sha256", "dataset_sha256"} <= set(run["hashes"])
    assert all(len(run["hashes"][k]) == 64 for k in ("knowledge_base_sha256", "manifest_sha256", "dataset_sha256"))
    assert set(run["versions"]) == {"retriever", "evaluator", "dataset"}
    result = run["results"][0]
    for key in ("query", "os", "expected_doc_ids", "prohibited_doc_ids", "retrieved", "missing_ids", "prohibited_matches",
                "precision", "recall", "result", "explanation", "fault"):
        assert key in result
    assert all("lexical_score" in h and "doc_id" in h and "rank" in h for h in result["retrieved"])
    unanswerable = run["results"][1]
    assert unanswerable["case_id"] == "R09" and unanswerable["precision"] is None and unanswerable["recall"] is None


def test_fault_runs_are_labelled_in_both_files(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01", "--fault", "obsolete-first")
    run = next(iter(reports_dir().values()))
    markdown = (paths.REPORTS_DIR / run["run_id"] / "report.md").read_text()

    assert run["label"] == "SYNTHETIC FAULT INJECTION" and run["fault"]["status"] == "APPLIED"
    assert markdown.startswith("# Day 5 retrieval evaluation") and "SYNTHETIC FAULT INJECTION: obsolete-first. Fault status: APPLIED" in markdown
    assert "not confidence probabilities" in markdown


def test_a_fault_that_cannot_apply_is_reported_as_not_applied(run_cli, reports_dir):
    code, out, _ = run_cli("evaluate", "--cases", "R03", "--fault", "obsolete-first")
    run = next(iter(reports_dir().values()))
    markdown = (paths.REPORTS_DIR / run["run_id"] / "report.md").read_text()

    assert "NOT APPLIED" in out and "no fault demonstration can be claimed" in out
    assert run["fault"]["status"] == "NOT APPLIED" and run["results"][0]["fault"]["status"] == "NOT APPLIED"
    assert "Fault status: NOT APPLIED" in markdown


# ------------------------------------------------------------------ never overwrite

def test_runs_get_unique_folders(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01")
    run_cli("evaluate", "--cases", "R01")

    assert len(reports_dir()) == 2


def test_an_existing_run_folder_is_never_overwritten(run_cli, reports_dir, monkeypatch):
    monkeypatch.setattr(report, "new_run_id", lambda: "eval-fixed-id")
    assert run_cli("evaluate", "--cases", "R01")[0] in (0, 1)  # completed, so it was saved either way
    before = {p.name: p.read_bytes() for p in (paths.REPORTS_DIR / "eval-fixed-id").iterdir()}

    code, _, err = run_cli("evaluate", "--cases", "R02")

    assert code == 2 and "never overwritten" in err
    assert {p.name: p.read_bytes() for p in (paths.REPORTS_DIR / "eval-fixed-id").iterdir()} == before


# ------------------------------------------------------------------ summary

def test_summary_latest_shows_the_source_run_and_fault_mode(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01")
    run_cli("evaluate", "--cases", "R01", "--fault", "wrong-os")
    runs = sorted(reports_dir().values(), key=lambda r: r["created_at"])

    code, out, _ = run_cli("summary", "--run", "latest")

    assert code == 0
    assert f"Source run: {runs[1]['run_id']}" in out and "Fault mode: wrong-os" in out and "Fault application: APPLIED" in out
    assert "SYNTHETIC FAULT INJECTION" in out
    first = run_cli("summary", "--run", runs[0]["run_id"])[1]
    assert f"Source run: {runs[0]['run_id']}" in first and "Fault mode: none" in first and "SYNTHETIC" not in first


def test_summary_without_any_run_is_a_clear_error(run_cli):
    code, _, err = run_cli("summary", "--run", "latest")

    assert code == 2 and "No saved evaluation exists" in err


def test_summary_refuses_corrupted_or_ambiguous_runs(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01")
    run_cli("evaluate", "--cases", "R01")
    for run_id in reports_dir():
        path = paths.REPORTS_DIR / run_id / "results.json"
        data = json.loads(path.read_text())
        data["created_at"] = "2030-01-01T00:00:00.000000Z"
        path.write_text(json.dumps(data))
    assert "Ambiguous" in run_cli("summary", "--run", "latest")[2]

    broken = paths.REPORTS_DIR / "eval-broken"
    broken.mkdir()
    (broken / "results.json").write_text("{not json")
    assert "corrupted" in run_cli("summary", "--run", "latest")[2]


def test_summary_flags_a_dataset_that_changed_after_the_run(run_cli, passing_dataset):
    run_cli("evaluate", "--cases", "all")
    passing_dataset.write_text(passing_dataset.read_text() + "\n")

    out = run_cli("summary", "--run", "latest")[1]

    assert "VERSION DRIFT" in out and "dataset" in out


# ------------------------------------------------------------------ validate and show commands

def test_validate_and_listing_commands_work_on_the_real_files(run_cli):
    assert run_cli("validate")[0] == 0
    out = run_cli("list-docs")[1]
    statuses = [line.split()[2] for line in out.splitlines()[1:]]  # the status column, not file names
    assert statuses.count("approved") == 6 and statuses.count("obsolete") == 2
    doc = run_cli("show-doc", "--id", "KB-VPN-MAC-CURRENT")[1]
    assert "Quit and reopen the approved VPN client." in doc and "Synthetic training material" in doc
    case = run_cli("show-case", "--id", "R07")[1]
    assert "KB-SUPPORT-ESCALATION" in case and "answer key" in case


def test_validate_fails_when_the_policy_file_is_missing(run_cli, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "POLICY_PATH", tmp_path / "missing.md")

    code, out, _ = run_cli("validate")

    assert code == 2 and "Missing retrieval policy" in out


# ------------------------------------------------------------------ real data smoke run

def test_the_real_evaluation_completes_and_saves_without_requiring_every_case_to_pass(run_cli, reports_dir):
    code, _, _ = run_cli("evaluate", "--cases", "all", "--top-k", "3")
    run = next(iter(reports_dir().values()))
    agg = run["aggregates"]

    assert code in (0, 1)  # the lexical baseline is allowed to fail some cases; labels are never changed to avoid that
    assert agg["cases"] == 10 and agg["answerable_cases"] == 8 and agg["unanswerable_cases"] == 2
    assert agg["passed"] + agg["failed"] == 10
    assert (code == 0) == (agg["failed"] == 0)
    assert run["fault"]["mode"] == "none" and run["label"] is None
