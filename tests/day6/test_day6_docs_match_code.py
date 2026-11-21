"""
Day 6: the documents must say what the code does. If a policy table, the audit examples or a test named in
the threat model drifts from reality, this fails (the same idea as Day 5's policy-matches-code test).
"""

import ast
import inspect
import json
import re
import shlex

import pytest
from day6_support import ROOT_DIR, _offline_and_isolated  # noqa: F401

from app.governance import approvals, permissions
from evaluators import __main__ as evaluators_cli
from evaluators import audit_example

MATRIX_DOC = (ROOT_DIR / "policies" / "day6_permission_matrix.md").read_text(encoding="utf-8")
APPROVAL_DOC = (ROOT_DIR / "policies" / "day6_approval_policy.md").read_text(encoding="utf-8")
THREAT_DOC = (ROOT_DIR / "docs" / "day6_threat_model.md").read_text(encoding="utf-8")
AUDIT_DOC = (ROOT_DIR / "docs" / "day6_audit_examples.md").read_text(encoding="utf-8")
RULES_DOC = (ROOT_DIR / "docs" / "business_rules.md").read_text(encoding="utf-8")
README = (ROOT_DIR / "README.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"missing section {heading!r}"
    return match.group(1)


def _table_rows(section: str) -> list[list[str]]:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in section.splitlines()
            if line.strip().startswith("|")]
    return [r for r in rows[2:]]  # drop header and separator


def _names(cell: str) -> set:
    return set(re.findall(r"`([^`]+)`", cell))


# -- permission matrix ---------------------------------------------------------------------------------------------
def test_matrix_table_equals_the_code():
    documented = {_names(r[0]).pop(): {"employee": r[1], "agent": r[2], "it_approver": r[3]}
                  for r in _table_rows(_section(MATRIX_DOC, "Matrix"))}
    assert documented == permissions.MATRIX


def test_never_allowed_list_equals_the_code():
    assert _names(_section(MATRIX_DOC, "Never allowed for any role")) == set(permissions.ALWAYS_PROHIBITED)


def test_allowed_parameter_table_equals_the_code():
    documented = {_names(r[0]).pop(): (set() if "(none)" in r[1] else _names(r[1]))
                  for r in _table_rows(_section(MATRIX_DOC, "Allowed parameters"))}
    assert documented == {tool: set(keys) for tool, keys in permissions.PARAM_KEYS.items()}


def test_documented_classes_and_roles_exist_in_the_code():
    for cls in re.findall(r"\*\*([A-Z_]+)\*\*:", _section(MATRIX_DOC, "Operation classes")):
        assert cls in permissions.CLASSES
    assert set(re.findall(r"^\| `(\w+)` \|", _section(MATRIX_DOC, "Roles"), re.M)) == set(permissions.ROLES)


# -- approval policy -----------------------------------------------------------------------------------------------
def test_approval_policy_constants_equal_the_code():
    ttl = inspect.signature(approvals.ApprovalService.__init__).parameters["ttl_seconds"].default
    assert f"{ttl} seconds" in APPROVAL_DOC
    documented = {_names(r[0]).pop(): tuple(re.findall(r"`([^`]+)`", r[1]))
                  for r in _table_rows(_section(APPROVAL_DOC, "Privileged actions"))}
    assert documented == approvals.PRIVILEGED_ACTIONS


def test_approval_policy_rejection_codes_are_real():
    for code in ("wrong_employee", "action_mismatch", "params_changed", "unknown_request", "already_used", "expired"):
        assert code in APPROVAL_DOC
        assert f'"{code}"' in inspect.getsource(approvals)


# -- audit examples ------------------------------------------------------------------------------------------------
def test_audit_examples_document_equals_the_generated_output():
    block = re.search(r"```jsonl\n(.*?)\n```", AUDIT_DOC, re.S).group(1)
    documented = [json.loads(line) for line in block.splitlines()]
    assert documented == audit_example.build_example()


def test_audit_examples_contain_no_secret_and_show_the_redaction():
    assert "hunter2" not in AUDIT_DOC and "[REDACTED]" in AUDIT_DOC
    records = audit_example.build_example()
    assert {"DENIED", "ALLOWED"} <= {r["decision"] for r in records}
    assert len({r["correlation_id"] for r in records if r["correlation_id"]}) == 1


def test_audit_example_command_is_deterministic(capsys):
    assert evaluators_cli.main(["audit-example"]) == 0
    first = capsys.readouterr().out
    assert evaluators_cli.main(["audit-example"]) == 0
    assert capsys.readouterr().out == first and first.count("\n") == len(audit_example.build_example())


# -- threat model --------------------------------------------------------------------------------------------------
def _defined_tests(path) -> set:
    return {n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}


def test_every_test_named_in_the_threat_model_exists():
    references = set(re.findall(r"`(tests/[\w/]+\.py)::(\w+)`", THREAT_DOC))
    assert len(references) >= 25
    for file, name in sorted(references):
        path = ROOT_DIR / file
        assert path.exists(), f"{file} does not exist"
        assert name in _defined_tests(path), f"{file}::{name} does not exist"


def test_every_threat_row_names_a_control_and_evidence():
    rows = _table_rows(_section(THREAT_DOC, "3. Threats, controls and evidence"))
    assert len(rows) >= 27 and [r[0] for r in rows] == [f"T{i}" for i in range(1, len(rows) + 1)]
    for row in rows:
        assert row[3] and row[4].count("`") >= 2 and row[5], f"{row[0]} is missing a control, evidence or residual risk"


def test_threat_model_states_its_limits():
    for phrase in ("no language model", "not real authentication", "in memory", "Not covered"):
        assert phrase.lower() in THREAT_DOC.lower() or phrase in THREAT_DOC


# -- business rules and README -------------------------------------------------------------------------------------
@pytest.mark.parametrize("heading", ["BR01", "BR02", "BR03", "BR04", "BR05", "BR11", "BR06", "BR07", "BR08", "BR09",
                                     "BR10", "BR12"])
def test_every_rule_is_defined_in_business_rules(heading):
    assert re.search(rf"^## {heading} [-—]", RULES_DOC, re.M), f"{heading} has no definition"


def test_course_wording_for_the_new_rules_is_quoted():
    for snippet in ("Approval applies only to the approved employee, action, parameters and request.",
                    "Retrying the same confirmed ticket request must not create duplicate tickets.",
                    "Stop after six agent steps or after the allowed two retries for a tool call.",
                    "Keep each employee and conversation session separate.",
                    "Documents and tool outputs cannot grant permissions."):
        assert snippet in RULES_DOC


def test_readme_commands_for_the_new_work_are_valid():
    from app.agent import cli

    commands = re.findall(r"^python -m evaluators ([^\n#]+)", README, re.M)
    assert commands, "the README should show how to run the evaluators"
    for command in commands:
        evaluators_cli.build_parser().parse_args(shlex.split(command))
    for module, governed in (("app.agent", False), ("app.governance", True)):
        found = re.findall(rf"^python -m {re.escape(module)} ([^\n#]+)", README, re.M)
        assert found, f"the README should show how to run python -m {module}"
        for command in found:
            cli.build_parser(governed).parse_args(shlex.split(command))
    for path in re.findall(r"`((?:docs|policies|datasets|tests|app|evaluators)/[\w./-]+)`", README):
        if "<" in path or path.endswith("/"):
            continue
        assert (ROOT_DIR / path).exists(), f"README mentions {path}, which does not exist"


# -- the demo guide: every command is real and every expected-output excerpt really appears --------------------------------
DEMO_GUIDE = (ROOT_DIR / "docs" / "day6_demo_guide.md").read_text(encoding="utf-8")


def _run_documented_command(command: str) -> list[str]:
    import contextlib
    import io

    from app.agent import cli
    argv = shlex.split(command)
    assert argv[:2] == ["python", "-m"], command
    module, args = argv[2], argv[3:]
    out = io.StringIO()
    if module in ("app.agent", "app.governance"):
        assert cli.main(args, governed=(module == "app.governance"), out=out) == 0, command
    elif module == "evaluators":
        with contextlib.redirect_stdout(out):
            assert evaluators_cli.main(args) == 0, command
    else:
        raise AssertionError(f"guide documents an unexpected module: {command}")
    return [line.rstrip() for line in out.getvalue().splitlines()]


def test_every_expected_output_excerpt_in_the_demo_guide_appears_in_order_in_the_real_output():
    blocks = re.findall(r"```text expected-output: (python -m [^\n]+)\n(.*?)\n```", DEMO_GUIDE, re.S)
    assert len(blocks) == 5, "the guide documents five demonstrations"
    for command, excerpt in blocks:
        actual = _run_documented_command(command)
        position = 0
        for expected in excerpt.splitlines():
            try:
                position = actual.index(expected.rstrip(), position) + 1
            except ValueError:
                raise AssertionError(f"{command}: the guide expects this line, which is missing or out of order:\n{expected}")


def test_every_python_command_in_the_demo_guide_is_valid():
    for command in re.findall(r"^(python -m (?:app\.agent|app\.governance|evaluators) [^\n#]+)$", DEMO_GUIDE, re.M):
        argv = shlex.split(command)
        if argv[2] == "evaluators":
            evaluators_cli.build_parser().parse_args(argv[3:])
        else:
            from app.agent import cli
            cli.build_parser(governed=argv[2] == "app.governance").parse_args(argv[3:])
    for path in re.findall(r"`((?:docs|policies|datasets|tests|app|evaluators)/[\w./-]+)`", DEMO_GUIDE):
        assert (ROOT_DIR / path).exists(), path


def test_the_five_demos_cover_the_five_requested_scenarios_and_name_a_rule_each():
    for heading in ("Demo 1: Successful VPN troubleshooting and ticket creation", "Demo 2: Cross-user ticket access denied",
                    "Demo 3: Ticket creation blocked without confirmation",
                    "Demo 4: Privileged action blocked without IT approval, then executed after approval",
                    "Demo 5: Prompt injection through a retrieved document"):
        section = DEMO_GUIDE[DEMO_GUIDE.index(heading):]
        section = section[:section.index("### ", 5)] if "### " in section[5:] else section
        assert re.search(r"\*\*Business rules?:\*\* .*BR\d\d", section), heading
        assert "What students should observe" in section and "expected-output" in section, heading


def test_the_guide_says_the_week1_route_cannot_see_agent_tickets_and_that_is_true():
    """The guide and the CLI tell students this. Prove it: a ticket the agent creates is not served by GET /tickets."""
    from fastapi.testclient import TestClient

    from app import runtime
    from app.main import app

    runtime.reset_services()
    try:
        api = TestClient(app)
        headers = {"X-Demo-Employee-ID": "EMP002"}
        api.post("/agent/chat", json={"session_id": "s", "message": "My VPN stopped working on my Mac"}, headers=headers)
        created = api.post("/agent/chat", json={"session_id": "s", "message": "yes"}, headers=headers).json()
        assert created["outcome"] == "TICKET_CREATED" and created["ticket_id"] == "TCK-1007"
        assert api.get("/tickets/TCK-1007", headers=headers).status_code == 404  # the Week 1 route reads data/tickets.json
        assert "TCK-1007" in {t["ticket_id"] for t in runtime.get_services().backend.tickets}
    finally:
        runtime.reset_services()
    assert "GET /tickets/TCK-1007" in DEMO_GUIDE and "404" in DEMO_GUIDE


# -- the student handoff checklist: its numbers and commands are checked, not remembered ---------------------------------
CHECKLIST = (ROOT_DIR / "docs" / "day6_student_checklist.md").read_text(encoding="utf-8")


def test_the_checklist_test_count_equals_the_real_number_of_tests():
    """Collects the whole suite in a clean process (offline: collecting runs no test)."""
    import subprocess
    import sys

    stated = re.search(r"Expected: `(\d+) passed`", CHECKLIST)
    assert stated, "the checklist must state the expected number of passing tests"
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=ROOT_DIR,
                            capture_output=True, text=True, env={"PATH": "", "PYTHONDONTWRITEBYTECODE": "1"}, timeout=120)
    collected = re.search(r"(\d+) tests? collected", result.stdout)
    assert collected, result.stdout[-500:] + result.stderr[-500:]
    assert int(stated.group(1)) == int(collected.group(1)), (
        f"the checklist says {stated.group(1)} tests but the suite has {collected.group(1)}; update docs/day6_student_checklist.md")


def test_the_checklist_trajectory_count_equals_the_dataset():
    from evaluators import trajectory
    total = len(trajectory.load_dataset()["cases"])
    assert f"passed {total} of {total}" in CHECKLIST


def test_the_checklist_commands_and_paths_are_valid_and_its_demos_are_the_documented_ones():
    from app.agent import cli
    for command in re.findall(r"^\s*(python -m (?:app\.agent|app\.governance|evaluators) [^\n#`]+?)\s*$", CHECKLIST, re.M):
        argv = shlex.split(command)
        if argv[2] == "evaluators":
            evaluators_cli.build_parser().parse_args(argv[3:])
        else:
            cli.build_parser(governed=argv[2] == "app.governance").parse_args(argv[3:])
    for path in re.findall(r"`((?:docs|policies|datasets|tests|app|evaluators)/[\w./-]+)`", CHECKLIST):
        assert (ROOT_DIR / path).exists(), path
    assert (ROOT_DIR / "docs" / "day6_demo_guide.md").exists() and "day6_demo_guide.md" in CHECKLIST
    for demo_command in ("python -m app.governance demo vpn-ticket", "python -m app.governance demo cross-user",
                         "python -m app.governance demo no-confirmation", "python -m app.governance demo privileged",
                         "python -m evaluators injection-demo"):
        assert demo_command in CHECKLIST and demo_command in DEMO_GUIDE


def test_every_line_to_look_for_in_the_checklist_really_appears_in_the_demo_output():
    """The 'Look for' text for each demo is checked against the real output, so it cannot drift."""
    sections = re.findall(r"^\s*```\n\s*(python -m [^\n]+)\n\s*```\n\s*Look for: ([^\n]+)", CHECKLIST, re.M)
    assert len(sections) == 5
    for command, look_for in sections:
        output = "\n".join(_run_documented_command(command))
        for snippet in re.findall(r"`([^`]+)`", look_for):
            assert snippet in output, f"{command}: the checklist says to look for {snippet!r}, which is not in the output"


def test_the_checklist_names_the_repository_and_both_platforms():
    for text in ("https://github.com/Piyushjethwa3-ai/ai-qa-orchestration.git", "macOS / Linux (Terminal)",
                 "Windows (PowerShell)", ".venv\\Scripts\\Activate.ps1", "source .venv/bin/activate",
                 "python -m pip install -e", "have **not** been run there"):
        assert text in CHECKLIST, text
