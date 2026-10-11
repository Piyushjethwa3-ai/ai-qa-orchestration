"""
Day 3: the `run` and `review` commands, end to end, in a temporary folder.
"""

import json

import pytest

from day3_lab.dataset import sha256_text


@pytest.fixture()
def demo_run(tmp_path, run_cli):
    out = tmp_path / "demo"
    code, _, _ = run_cli("run", "--mode", "mock", "--case", "D3-01", "--out", out)
    assert code == 0
    return out


def test_mock_run_saves_required_evidence(demo_run, read_json):
    run = read_json(demo_run / "run.json")
    record = run["records"][0]

    assert (demo_run / "run.html").exists()
    for key in ("run_id", "created_at", "git", "provider_mode", "model", "prompt", "dataset", "rubric"):
        assert key in run
    assert run["provider_mode"] == "MOCK"
    assert run["model"] is None
    assert len(run["prompt"]["sha256"]) == 64 and len(run["dataset"]["sha256"]) == 64
    assert run["rubric"]["version"] == "day3-v1"
    assert "commit" in run["git"] and "dirty" in run["git"]
    assert record["case"]["approved_context"]["service_status"] == "outage"
    assert record["raw_response"] and record["parsed_response"]
    assert record["response_hash"] == sha256_text(record["raw_response"])
    assert record["provider"]["token_usage"] is None  # never invented for mock
    assert "NOT model latency" in record["provider"]["elapsed_note"]
    assert record["human_assessment"] == {"status": "PENDING", "current": None, "history": []}
    assert record["outcome"]["result"] == "REVIEW_PENDING"


def test_full_mock_run_has_ten_mock_records_all_pending(tmp_path, run_cli, read_json):
    code, _, _ = run_cli("run", "--mode", "mock", "--out", tmp_path / "guided")
    run = read_json(tmp_path / "guided" / "run.json")

    assert code == 0
    assert len(run["records"]) == 10
    assert {record["source"] for record in run["records"]} == {"MOCK"}
    assert {record["structural"]["result"] for record in run["records"]} == {"PASS"}
    assert {record["outcome"]["result"] for record in run["records"]} == {"REVIEW_PENDING"}
    assert "MOCK" in (tmp_path / "guided" / "run.html").read_text()


def test_run_refuses_to_overwrite_an_earlier_run(demo_run, run_cli):
    before = (demo_run / "run.json").read_bytes()

    code, _, err = run_cli("run", "--mode", "mock", "--case", "D3-01", "--out", demo_run)

    assert code == 2
    assert "fresh output directory" in err
    assert (demo_run / "run.json").read_bytes() == before


def test_unknown_case_is_refused(tmp_path, run_cli):
    code, _, err = run_cli("run", "--mode", "mock", "--case", "D3-99", "--out", tmp_path / "x")

    assert code == 2
    assert "Unknown case" in err
    assert not (tmp_path / "x" / "run.json").exists()


def test_review_binds_identity_timestamp_and_response_hash(demo_run, run_cli, read_json):
    code, out, _ = run_cli(
        "review", "--report", demo_run / "run.json", "--case", "D3-01",
        "--scores", "2", "2", "2", "2", "--critical", "no", "--note", "Supported by supplied context.",
        "--reviewer", "trainer-01",
    )
    record = read_json(demo_run / "run.json")["records"][0]
    current = record["human_assessment"]["current"]

    assert code == 0
    assert current["reviewer"] == "trainer-01"
    assert current["reviewed_at"].endswith("Z")
    assert current["response_hash"] == record["response_hash"]
    assert current["scores"] == {"correctness": 2, "relevance": 2, "completeness": 2, "safety": 2}
    assert current["critical"] is False
    assert record["outcome"]["result"] == "PASS"
    assert "Supported by supplied context." in (demo_run / "run.html").read_text()


def test_review_defaults_to_os_user_identifier(demo_run, run_cli, read_json):
    run_cli("review", "--report", demo_run / "run.json", "--case", "D3-01",
            "--scores", "2", "2", "2", "2", "--critical", "no", "--note", "ok")
    current = read_json(demo_run / "run.json")["records"][0]["human_assessment"]["current"]

    assert current["reviewer"]
    assert current["reviewer_source"] == "operating-system user name"


def test_second_review_is_appended_to_history(demo_run, run_cli, read_json):
    report = demo_run / "run.json"
    run_cli("review", "--report", report, "--case", "D3-01", "--scores", "2", "2", "2", "2",
            "--critical", "no", "--note", "first look")
    run_cli("review", "--report", report, "--case", "D3-01", "--scores", "1", "2", "2", "2",
            "--critical", "no", "--note", "on second reading, ambiguous")
    human = read_json(report)["records"][0]["human_assessment"]

    assert [h["note"] for h in human["history"]] == ["first look", "on second reading, ambiguous"]
    assert human["current"]["note"] == "on second reading, ambiguous"
    assert read_json(report)["records"][0]["outcome"]["result"] == "FAIL"


@pytest.mark.parametrize(
    "scores",
    [["3", "2", "2", "2"], ["-1", "2", "2", "2"], ["2.0", "2", "2", "2"], ["two", "2", "2", "2"], ["2", "2", "2"]],
)
def test_cli_rejects_invalid_scores_and_changes_nothing(demo_run, run_cli, scores):
    before = (demo_run / "run.json").read_bytes()

    code, _, _ = run_cli("review", "--report", demo_run / "run.json", "--case", "D3-01",
                         "--scores", *scores, "--critical", "no", "--note", "x")

    assert code == 2
    assert (demo_run / "run.json").read_bytes() == before


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(["--note", "x"], id="critical_missing"),
        pytest.param(["--critical", "maybe", "--note", "x"], id="critical_invalid"),
        pytest.param(["--critical", "no"], id="note_missing"),
        pytest.param(["--critical", "no", "--note", "   "], id="note_blank"),
    ],
)
def test_cli_requires_critical_flag_and_note(demo_run, run_cli, extra):
    code, _, _ = run_cli("review", "--report", demo_run / "run.json", "--case", "D3-01",
                         "--scores", "2", "2", "2", "2", *extra)

    assert code == 2


def test_label_is_not_transferred_to_a_changed_response(demo_run, run_cli, read_json):
    report = demo_run / "run.json"
    run_cli("review", "--report", report, "--case", "D3-01", "--scores", "2", "2", "2", "2",
            "--critical", "no", "--note", "good answer")

    # Someone swaps in a different response (and even updates its hash).
    run = read_json(report)
    record = run["records"][0]
    record["raw_response"] = record["raw_response"].replace("No recovery time has been published yet.",
                                                            "It will be fixed in 30 minutes.")
    record["response_hash"] = sha256_text(record["raw_response"])
    report.write_text(json.dumps(run))

    # Any later review triggers a refresh; the old PASS must not carry over.
    code, _, _ = run_cli("review", "--report", report, "--case", "D3-01", "--scores", "0", "2", "2", "2",
                         "--critical", "no", "--note", "invented ETA")
    record = read_json(report)["records"][0]
    assert code == 0
    assert record["human_assessment"]["history"][0]["response_hash"] != record["response_hash"]
    assert record["outcome"]["result"] == "FAIL"


def test_stale_label_makes_record_review_pending(demo_run, run_cli, read_json):
    from day3_lab.assessment import decide_outcome

    report = demo_run / "run.json"
    run_cli("review", "--report", report, "--case", "D3-01", "--scores", "2", "2", "2", "2",
            "--critical", "no", "--note", "good answer")
    record = read_json(report)["records"][0]
    record["raw_response"] += " "
    record["response_hash"] = sha256_text(record["raw_response"])

    assert decide_outcome(record)["result"] == "REVIEW_PENDING"


def test_review_refused_when_response_text_no_longer_matches_its_hash(demo_run, run_cli, read_json):
    report = demo_run / "run.json"
    run = read_json(report)
    run["records"][0]["raw_response"] += " tampered"  # hash left unchanged
    report.write_text(json.dumps(run))
    before = report.read_bytes()

    code, _, err = run_cli("review", "--report", report, "--case", "D3-01", "--scores", "2", "2", "2", "2",
                           "--critical", "no", "--note", "x")

    assert code == 2
    assert "no longer matches" in err
    assert report.read_bytes() == before


def test_open_uses_standard_library_browser(demo_run, run_cli, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda uri: opened.append(uri) or True)

    code, _, _ = run_cli("open", demo_run / "run.html")

    assert code == 0
    assert opened and opened[0].startswith("file://") and opened[0].endswith("run.html")


def test_open_missing_file_is_refused(tmp_path, run_cli):
    code, _, _ = run_cli("open", tmp_path / "nope" / "run.html")

    assert code == 2
