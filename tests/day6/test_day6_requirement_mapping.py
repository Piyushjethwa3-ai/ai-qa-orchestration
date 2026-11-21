"""
Day 6: the BR03/BR04 resolution and the coverage of all twelve rules.

The course catalogue BR01-BR12 is canonical. The two Week 1 rules that used the numbers BR03 and BR04 are labelled
API-R03 and API-R04. Day 3 and Day 4 find defined rule IDs with the heading pattern `^## (BR\\d{2})`, so the resolution
must keep every ID defined exactly once and must not break either tool.
"""

import json
import re
from collections import Counter

import pytest
from day6_support import ROOT_DIR, _offline_and_isolated  # noqa: F401

from day3_lab import dataset as day3_dataset
from training_day4 import checks as day4_checks

RULES = (ROOT_DIR / "docs" / "business_rules.md").read_text(encoding="utf-8")
ALL_RULES = [f"BR{n:02d}" for n in range(1, 13)]
DATASETS = {"A": "datasets/agent/trajectory_cases.json", "B": "datasets/agent/trajectory_cases.json",
            "D3": "datasets/day3/cases.json", "D4": "datasets/day4/cases.json"}


def _cases(path):
    return {c["case_id"]: c for c in json.loads((ROOT_DIR / path).read_text(encoding="utf-8"))["cases"]}


def _section(heading_start: str) -> str:
    match = re.search(rf"^## {re.escape(heading_start)}.*?\n(.*?)(?=^## |^# |\Z)", RULES, re.S | re.M)
    assert match, heading_start
    return match.group(1)


# -- rule discovery still works ---------------------------------------------------------------------------------------
def test_the_day3_and_day4_tools_discover_all_twelve_rules_exactly_once():
    assert day3_dataset._defined_business_rules() == set(ALL_RULES)
    assert day4_checks.defined_business_rules() == set(ALL_RULES)
    headings = re.findall(r"^## (BR\d{2})\b", RULES, flags=re.M)
    assert sorted(headings) == ALL_RULES, f"each rule must be defined once: {Counter(headings)}"


def test_the_week1_rules_are_labelled_api_r_and_are_not_discoverable_as_course_rules():
    assert re.findall(r"^## (API-R\d{2})\b", RULES, flags=re.M) == ["API-R03", "API-R04"]
    assert not re.search(r"^## BR0[34] [-—] (A missing ticket|VPN service status)", RULES, flags=re.M)
    assert "## API-R03 — A missing ticket returns 404" in RULES
    assert "## API-R04 — VPN service status has a defined status and update time" in RULES
    assert "returns `404 Not Found`" in _section("API-R03") and "`updated_at`" in _section("API-R04")


def test_the_course_meanings_are_what_the_canonical_headings_say():
    assert "Do not invent a recovery time." in _section("BR03 -")
    assert "Clarify or escalate when" in _section("BR04 -")
    assert "Check current service status for a possible outage." in RULES


def test_nothing_was_lost_the_week1_rule_text_is_still_in_the_document():
    for snippet in ("If no ticket with the requested `ticket_id` exists at all", "returns `404 Not Found`",
                    "`status`: one of `operational`, `degraded`, or `outage`.", "`updated_at`: an ISO 8601 timestamp"):
        assert snippet in RULES


# -- the alias table ------------------------------------------------------------------------------------------------------
def _week1_files():
    candidates = list((ROOT_DIR / "tests" / "day2").glob("*.py")) + list((ROOT_DIR / "tests").glob("test_*.py")) + \
                 list((ROOT_DIR / "docs").glob("day2-*.md"))  # app/main.py now uses the new labels (checked separately)
    return [p for p in candidates if re.search(r"\bBR0?[34]\b", p.read_text(encoding="utf-8"))]


def test_every_file_that_still_uses_the_week1_meaning_is_listed_in_the_alias_table():
    table = RULES[RULES.index("| File that still uses the Week 1 meaning"):RULES.index("The two headings that start")]
    listed = set(re.findall(r"`([^`]+)`", table))
    found = {str(p.relative_to(ROOT_DIR)) for p in _week1_files()}
    assert found == listed, f"unlisted: {found - listed}; listed but not found: {listed - found}"


def test_the_week1_code_comments_use_the_new_labels():
    main = (ROOT_DIR / "app" / "main.py").read_text(encoding="utf-8")
    assert "API-R03 (labelled BR03 in Week 1)" in main and "API-R04 (labelled BR04 in Week 1)" in main
    assert not re.search(r"^\s+BR0[34]:", main, re.M)


# -- every case cited for BR03/BR04 really carries that rule ------------------------------------------------------------------
def _cited_case_ids(section: str) -> set:
    ids = set(re.findall(r"\b(?:D3-\d\d|D4-\d\d|A-\d\d)\b", section))
    for prefix, lo, hi in re.findall(r"\b(A|D3|D4)-(\d\d) to (?:A|D3|D4)-(\d\d)\b", section):  # "A-02 to A-06"
        ids |= {f"{prefix}-{n:02d}" for n in range(int(lo), int(hi) + 1)}
    return ids


def _dataset_for(case_id: str) -> str:
    return "datasets/agent/trajectory_cases.json" if case_id.startswith("A-") else (
        "datasets/day3/cases.json" if case_id.startswith("D3-") else "datasets/day4/cases.json")


@pytest.mark.parametrize("rule", ["BR03", "BR04"])
def test_every_case_cited_in_the_canonical_section_carries_that_rule(rule):
    cited = _cited_case_ids(_section(f"{rule} -"))
    assert cited, "the section should cite cases"
    for case_id in sorted(cited):
        assert rule in _cases(_dataset_for(case_id))[case_id]["requirement_ids"], f"{case_id} does not carry {rule}"


@pytest.mark.parametrize("rule", ["BR03", "BR04"])
def test_every_case_that_carries_the_rule_is_cited(rule):
    cited = _cited_case_ids(_section(f"{rule} -"))
    for path in ("datasets/agent/trajectory_cases.json", "datasets/day3/cases.json", "datasets/day4/cases.json"):
        carrying = {cid for cid, c in _cases(path).items() if rule in c["requirement_ids"]}
        assert carrying <= cited, f"{rule}: {sorted(carrying - cited)} carry it but the document does not cite them"


# -- all twelve rules have evaluation coverage ------------------------------------------------------------------------------------
TRAJECTORY = _cases("datasets/agent/trajectory_cases.json")
SECURITY_TESTS = {  # rules that also have direct, non-trajectory tests, named so the claim can be checked
    "BR01": ["tests/day6/test_day6_api.py::test_identity_cannot_be_changed_by_the_request_body_or_chat_text"],
    "BR02": ["tests/day6/test_day6_enforcement.py::test_attack_is_refused_with_a_reason_and_exposes_nothing"],
    "BR05": ["tests/day6/test_day6_audit.py::test_secrets_in_parameters_and_errors_are_redacted_before_storage"],
    "BR06": ["tests/day6/test_day6_enforcement.py::test_attack_is_blocked_with_the_control_and_works_without_it"],
    "BR07": ["tests/day6/test_day6_enforcement.py::test_attack_is_blocked_with_the_control_and_works_without_it",
             "tests/day6/test_day6_permissions_approvals.py::test_approval_applies_only_to_the_approved_employee_action_and_parameters"],
    "BR08": ["tests/day6/test_day6_tool_boundary.py::test_a_retry_after_a_timeout_never_executes_twice_but_a_new_attempt_is_refused"],
    "BR09": ["tests/agent/test_agent_runner.py::test_step_limit_is_enforced_by_the_runner_not_the_planner"],
    "BR10": ["tests/agent/test_agent_runner.py::test_sessions_are_isolated_by_employee_and_by_session_id"],
    "BR11": ["tests/day6/test_day6_agent_security.py::test_unconfirmed_execution_is_reported_unknown_and_retry_does_not_run_it_twice"],
    "BR12": ["tests/day6/test_day6_injection.py::test_with_enforcement_every_attempt_is_refused_and_nothing_changes"],
}


@pytest.mark.parametrize("rule", ALL_RULES)
def test_every_rule_is_covered_by_trajectory_cases(rule):
    covering = sorted(cid for cid, c in TRAJECTORY.items() if rule in c["requirement_ids"])
    assert covering, f"{rule} has no trajectory case"


def test_br07_and_br12_are_covered_by_cases_that_make_real_attempts():
    for rule, must_have in (("BR07", "execute_privileged_action"), ("BR12", "decide_approval")):
        cases = [c for c in TRAJECTORY.values() if rule in c["requirement_ids"] and c["setup"].get("mode")]
        assert cases, rule
        assert any(must_have in c["expected_behaviour"]["tool_sequence"] for c in cases), (
            f"{rule}: no governed case attempts {must_have}")
    b01 = TRAJECTORY["B-01"]["expected_behaviour"]
    assert b01["tool_sequence"].count("execute_privileged_action") == 6  # six actual execution attempts
    assert b01["privileged_executions"] == 1 and "DENIED" in b01["trace_statuses"]


@pytest.mark.parametrize("rule", sorted(SECURITY_TESTS))
def test_the_direct_tests_named_for_each_rule_exist(rule):
    import ast
    for ref in SECURITY_TESTS[rule]:
        file, name = ref.split("::")
        names = {n.name for n in ast.walk(ast.parse((ROOT_DIR / file).read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}
        assert name in names, f"{ref} does not exist"


def test_the_week1_rules_keep_their_own_coverage():
    """API-R03 (missing ticket -> 404) and API-R04 (VPN status shape) are covered by the unchanged Day 1 and Day 2 tests."""
    import ast

    def functions(path):
        return {n.name: ast.get_source_segment((ROOT_DIR / path).read_text(encoding="utf-8"), n)
                for n in ast.walk(ast.parse((ROOT_DIR / path).read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}

    tickets = functions("tests/test_tickets.py")
    assert "404" in tickets["test_missing_ticket_returns_404"]                                  # API-R03
    assert "test_missing_ticket_error_matches_schema" in functions("tests/day2/test_04_schema.py")
    schema = functions("tests/day2/test_04_schema.py")
    assert "service_status" in schema["test_service_status_matches_schema"]                      # API-R04
    assert "def test_get_vpn_status" in (ROOT_DIR / "tests" / "test_service_status.py").read_text(encoding="utf-8") or \
        "vpn" in (ROOT_DIR / "tests" / "test_service_status.py").read_text(encoding="utf-8").lower()
