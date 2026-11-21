"""
Week 5 trajectory cases. Two jobs:

1. Every case in datasets/agent/trajectory_cases.json passes on the real agent.
2. The evaluator is NOT vacuous: with a fault seeded into the agent, the matching case FAILS.
   (A suite that cannot fail proves nothing.)
"""

import dataclasses
import json
import re

import pytest
from agent_support import MAC, _offline_and_isolated  # noqa: F401

from app.agent.confirmations import ConfirmationStore
from app.agent.planner import Reply, RulePlanner
from app.agent.runner import AgentRunner
from app.agent.sessions import SessionStore
from app.agent.stack import build_stack
from evaluators import __main__ as cli
from evaluators import trajectory

DATASET = trajectory.load_dataset()
CASES = {c["case_id"]: c for c in DATASET["cases"]}


def test_dataset_is_valid_and_large_enough():
    assert trajectory.validate_dataset(DATASET) == []
    assert len(CASES) >= 20
    covered = {r for c in DATASET["cases"] for r in c["requirement_ids"]}
    assert {f"BR{n:02d}" for n in range(1, 13)} <= covered  # all twelve rules
    assert all(c["evaluator_type"] == "trajectory" and c["fixture_version"] == "agent-v1" for c in CASES.values())


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_case_passes_on_the_real_agent(case_id):
    result = trajectory.evaluate_case(CASES[case_id])
    assert result["result"] == "PASS", result["findings"]


def test_summary_counts():
    summary = trajectory.summarise(trajectory.run_dataset())
    assert summary == {"total": len(CASES), "passed": len(CASES), "failed": 0, "failed_case_ids": [],
                       "critical_failed_case_ids": []}


# -- seeded faults: the evaluator must catch each one ---------------------------------------------------
def _factory(mutate):
    def make(setup):
        stack = trajectory.default_stack_factory(setup)
        mutate(stack)
        return stack
    return make


def _fails(case_id, mutate=None, **kwargs):
    factory = _factory(mutate) if mutate else (kwargs.pop("stack_factory", None) or trajectory.default_stack_factory)
    return trajectory.evaluate_case(CASES[case_id], factory)


def test_a_wrong_expectation_is_reported_as_fail_not_silently_passed():
    case = json.loads(json.dumps(CASES["A-07"]))
    case["expected_behaviour"]["tickets_created"] = 2
    result = trajectory.evaluate_case(case)
    assert result["result"] == "FAIL" and any("stored state" in f for f in result["findings"])


def test_detects_duplicate_tickets_when_idempotency_and_single_use_are_removed():
    class NoMemory(dict):
        def get(self, *a, **k):
            return None

    def break_it(stack):
        stack.backend._by_key = NoMemory()
        stack.confirmations.consume = lambda cid: None

    result = _fails("A-11", break_it)
    assert result["result"] == "FAIL" and result["tickets_created"] == 2


def test_detects_broken_ownership(monkeypatch):
    monkeypatch.setattr("app.agent.tools.rules.employee_owns_ticket", lambda ticket, employee_id: True)
    result = _fails("A-19")
    assert result["result"] == "FAIL" and any("prohibited text" in f for f in result["findings"])


def test_detects_a_missing_step_limit():
    result = _fails("A-17", lambda stack: setattr(stack.runner, "max_steps", 100))
    assert result["result"] == "FAIL"


def test_detects_a_missing_retry_limit():
    result = _fails("A-16", lambda stack: setattr(stack.runner, "max_retries", 0))
    assert result["result"] == "FAIL" and any("retries included" in f for f in result["findings"])


def test_detects_broken_session_isolation(monkeypatch):
    original = SessionStore.get
    monkeypatch.setattr(SessionStore, "get", lambda self, employee_id, session_id: original(self, "EMP001", session_id))
    assert _fails("A-24")["result"] == "FAIL"


def test_detects_missing_redaction(monkeypatch):
    monkeypatch.setattr("app.agent.runner.redact_text", lambda text: text)
    monkeypatch.setattr("app.agent.runner.redact", lambda value: value)
    result = _fails("A-21")
    assert result["result"] == "FAIL" and any("hunter2" in f for f in result["findings"])


def test_detects_a_planner_that_claims_success_it_did_not_get():
    class Lying(RulePlanner):
        def plan(self, turn):
            action = super().plan(turn)
            if isinstance(action, Reply) and action.outcome == "PENDING_CONFIRMATION":
                return dataclasses.replace(action, message=action.message + " Ticket TCK-9999 has been created.")
            return action

    def swap(stack):
        stack.runner = AgentRunner(stack.invoker, stack.sessions, stack.confirmations, Lying())

    assert _fails("A-03", swap)["result"] == "FAIL"


def test_detects_an_invented_recovery_time():
    class Inventing(RulePlanner):
        def plan(self, turn):
            action = super().plan(turn)
            if isinstance(action, Reply) and action.outcome == "OUTAGE_GUIDANCE":
                return dataclasses.replace(action, message=action.message + " It should be fixed in 30 minutes.")
            return action

    def swap(stack):
        stack.runner = AgentRunner(stack.invoker, stack.sessions, stack.confirmations, Inventing())

    assert _fails("A-01", swap)["result"] == "FAIL"


def test_detects_a_write_without_confirmation():
    class Eager(RulePlanner):
        def plan(self, turn):
            from app.agent.planner import ToolCall
            if turn.intent == "vpn" and not turn.observations:
                return ToolCall("create_ticket", {"subject": "x", "description": "y", "idempotency_key": "k",
                                                  "confirmation_id": "CONF-0001"})
            return super().plan(turn)

    def swap(stack):
        stack.runner = AgentRunner(stack.invoker, stack.sessions, stack.confirmations, Eager())

    result = _fails("A-03", swap)
    assert result["result"] == "FAIL" and result["tickets_created"] == 0  # the tool refused; the evaluator flagged it


# -- command line ---------------------------------------------------------------------------------------
def test_cli_saves_a_new_run_folder_and_never_overwrites(tmp_path):
    out = tmp_path / "agent"
    assert cli.main(["trajectories", "--out-dir", str(out), "--cases", "A-07", "A-11"]) == 0
    assert cli.main(["trajectories", "--out-dir", str(out), "--cases", "A-07"]) == 0
    folders = list(out.iterdir())
    assert len(folders) == 2  # the second run got its own folder
    runs = {json.loads((f / "results.json").read_text())["summary"]["total"]: (f, json.loads((f / "results.json").read_text()))
            for f in folders}
    folder, run = runs[2]
    assert set(runs) == {1, 2}
    assert run["model_used"] is None and run["mode"] == "LOCAL_DETERMINISTIC_RULE_BASED_AGENT"
    assert re.fullmatch(r"traj-\d{8}T\d{6}Z-[0-9a-f]{8}", run["run_id"])
    assert (folder / "report.md").read_text().startswith("# Agent trajectory run")
    assert run["summary"]["passed"] == 2


def test_cli_rejects_unknown_case_ids(tmp_path, capsys):
    assert cli.main(["trajectories", "--out-dir", str(tmp_path), "--cases", "NOPE"]) == 2
    assert not list(tmp_path.iterdir())
    assert "NOPE" in capsys.readouterr().err
