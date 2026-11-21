"""The two training command lines: `python -m app.agent` (Week 5, standalone) and `python -m app.governance` (Day 6)."""

import io
import subprocess
import sys

import pytest
from day6_support import ROOT_DIR, _offline_and_isolated  # noqa: F401

from app import data
from app.agent import cli

AGENT_DEMOS = ["vpn-ticket", "outage", "cross-user", "no-confirmation", "timeout-no-duplicate", "account-reset"]
GOVERNED_DEMOS = ["vpn-ticket", "outage", "cross-user", "no-confirmation", "timeout-no-duplicate", "privileged"]
MODES = [(False, name) for name in AGENT_DEMOS] + [(True, name) for name in GOVERNED_DEMOS]


def run(argv, governed=False, lines=()):
    out, feed = io.StringIO(), iter(lines)

    def input_fn(prompt=""):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    code = cli.main(argv, governed=governed, input_fn=input_fn, out=out)
    return code, out.getvalue()


def data_snapshot():
    return {p.name: p.read_bytes() for p in sorted(data.DATA_DIR.glob("*.json"))}


# -- discoverability -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("governed", [False, True])
def test_list_names_the_demonstrations_and_says_there_is_no_llm(governed):
    code, text = run(["list"], governed)
    names = GOVERNED_DEMOS if governed else AGENT_DEMOS
    assert code == 0 and all(name in text for name in names)
    assert "does NOT call an LLM" in text
    assert ("python -m evaluators injection-demo" in text) is governed  # only the governed CLI points at demo 5


@pytest.mark.parametrize("governed", [False, True])
def test_help_is_beginner_friendly(governed, capsys):
    assert run(["--help"], governed)[0] == 0
    help_text = capsys.readouterr().out
    prog = "python -m app.governance" if governed else "python -m app.agent"
    for text in ("does NOT call an LLM", "MEMORY only", "GET /tickets", "examples:", f"{prog} demo", f"{prog} chat",
                 "EMP001, EMP002, EMP003, EMP004"):
        assert text in help_text, text


def test_the_two_clis_offer_different_demos():
    assert "privileged" not in run(["list"], False)[1] and "account-reset" not in run(["list"], True)[1]


# -- every demonstration runs, offline, deterministically, and writes nothing ------------------------------------------------------
@pytest.mark.parametrize("governed, name", MODES)
def test_every_demo_runs_and_is_deterministic(governed, name):
    before = data_snapshot()
    code, first = run(["demo", name], governed)
    assert code == 0 and "What to observe:" in first and "Business rule(s):" in first
    assert run(["demo", name], governed)[1] == first  # same input, same output, every time
    assert data_snapshot() == before  # nothing was written to data/
    assert "does NOT call an LLM" in first and "MEMORY only" in first


def test_demo_all_runs_every_demo_for_each_cli():
    for governed, names in ((False, AGENT_DEMOS), (True, GOVERNED_DEMOS)):
        code, text = run(["demo", "all"], governed)
        assert code == 0 and text.count("What to observe:") == len(names)


# -- what each demonstration shows -----------------------------------------------------------------------------------------------
def test_demo_vpn_ticket_creates_one_in_memory_ticket_after_confirmation():
    _, text = run(["demo", "vpn-ticket"], True)
    assert text.index("PENDING_CONFIRMATION") < text.index("TICKET_CREATED")
    assert "Nothing has been created yet" in text and "TCK-1007" in text
    assert "get_service_status=SUCCESS -> retrieve_guide=SUCCESS -> search_tickets=SUCCESS" in text
    assert text.count("<- created in this session, in memory only") == 1


def test_demo_cross_user_returns_no_ticket_content_to_the_other_employee():
    _, text = run(["demo", "cross-user"], True)
    denied_part = text[text.index("[1]"):text.index("[3]")]
    assert "TICKET_UNAVAILABLE" in denied_part and "DENIED: not your ticket" in denied_part
    assert "VPN client fails" not in denied_part  # the denied steps never show the subject
    assert "SUCCESS: TCK-1001 'VPN client fails to connect from home network'" in text  # the control step does


@pytest.mark.parametrize("governed, first_refusal", [
    (False, "-> DENIED: confirmation required (unknown_confirmation)"),   # Week 5: the TOOL refuses a missing confirmation
    (True, "-> DENIED: employee confirmation is required"),                # Day 6: the GATEWAY refuses it first
])
def test_demo_no_confirmation_blocks_then_allows_with_a_real_confirmation(governed, first_refusal):
    _, text = run(["demo", "no-confirmation"], governed)
    for line in (first_refusal, "directly, with no confirmation", "with a made-up confirmation ID (CONF-9999)",
                 "-> DENIED: confirmation required (unknown_confirmation)", "with the employee's confirmation",
                 "SUCCESS: TCK-1007 'VPN problem'", "NEEDS_CLARIFICATION"):
        assert line in text, line
    assert text.index(first_refusal) < text.index("SUCCESS: TCK-1007")  # blocked first, allowed only after confirmation


def test_demo_privileged_blocks_until_it_approves_then_runs_once():
    _, text = run(["demo", "privileged"], True)
    order = ["Nothing has been reset", "PRIVILEGED_STATUS", "DENIED: approval not valid (pending)",
             "DENIED: not_an_approver", "APPROVED by APR001", "PRIVILEGED_EXECUTED", "DENIED: approval not valid (already_used)",
             "hash chain intact: True"]
    positions = [text.index(item) for item in order]
    assert positions == sorted(positions), "the demo steps happen in the wrong order"
    assert "No real account or password was changed" in text


def test_demo_timeout_no_duplicate_shows_a_retry_and_one_ticket():
    _, text = run(["demo", "timeout-no-duplicate"], False)
    assert "retries used: 1" in text and text.count("<- created in this session") == 1


def test_week5_account_reset_escalates_and_never_asks_for_secrets():
    _, text = run(["demo", "account-reset"], False)
    assert "ESCALATED" in text and "No reset has been requested or performed" in text
    assert "never ask you for your password" in text


# -- the standalone agent really is standalone -----------------------------------------------------------------------------------------
def test_the_week5_cli_loads_no_governance_code_except_redaction():
    code = ("import io, sys\nfrom app.agent import cli\n"
            "cli.main(['demo', 'vpn-ticket'], governed=False, out=io.StringIO())\n"
            "cli.main(['demo', 'no-confirmation'], governed=False, out=io.StringIO())\n"
            "print(sorted(m for m in sys.modules if m.startswith('app.governance')))")
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT_DIR, capture_output=True, text=True,
                            env={"PATH": "", "PYTHONPATH": str(ROOT_DIR)}, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['app.governance', 'app.governance.redaction']"


def test_python_dash_m_entry_points_work_in_a_clean_process():
    for module, expect in (("app.agent", "WEEK 5 AGENT"), ("app.governance", "DAY 6 GOVERNED AGENT")):
        result = subprocess.run([sys.executable, "-m", module, "demo", "vpn-ticket"], cwd=ROOT_DIR, capture_output=True,
                                text=True, env={"PATH": ""}, timeout=60)
        assert result.returncode == 0 and expect in result.stdout and "TICKET_CREATED" in result.stdout, result.stderr


# -- chat ---------------------------------------------------------------------------------------------------------------------------------
def test_one_shot_chat_runs_a_conversation_and_reports_status_choices():
    code, text = run(["chat", "--employee", "EMP002", "-m", "My VPN stopped working on my Mac", "-m", "yes"])
    assert code == 0 and "PENDING_CONFIRMATION" in text and "TICKET_CREATED" in text
    code, text = run(["chat", "--status", "outage", "-m", "My VPN is down for everyone"])
    assert code == 0 and "OUTAGE_GUIDANCE" in text and "recovery time" in text


def test_chat_rejects_an_unknown_employee_and_bad_input(capsys):
    assert run(["chat", "--employee", "EMP999", "-m", "hi"])[0] == 2
    assert "unknown employee 'EMP999'" in capsys.readouterr().err
    assert run(["chat", "-m", "   "])[0] == 2
    assert run(["demo", "no-such-demo"])[0] == 2
    assert run([])[0] == 2


def test_interactive_chat_commands():
    code, text = run(["chat", "--employee", "EMP002"],
                     lines=["My VPN stopped working on my Mac", "yes", "/tickets", "/as EMP001", "yes", "/as EMP999", "/trace",
                            "/bogus", "/help", "", "/quit"])
    assert code == 0
    for item in ("TICKET_CREATED", "created in this session, in memory only", "now acting as EMP001", "NOTHING_TO_CONFIRM",
                 "unknown employee", "tool trace on", "unknown command", "Commands:", "Goodbye. Nothing was written to data/."):
        assert item in text, item


def test_interactive_governed_chat_can_approve_and_audit():
    code, text = run(["chat", "--employee", "EMP001"], True,
                     lines=["I forgot my password and need a reset", "yes", "/approve looks fine", "/reject",
                            "what is the status of my reset request", "yes", "/audit"])
    assert code == 0
    assert "PRV-0001 -> APPROVED (decided by APR001)" in text and "refused: already_decided" in text
    assert "PRIVILEGED_EXECUTED" in text and "hash chain intact: True" in text


def test_the_week5_cli_has_no_approver_or_audit_commands():
    _, text = run(["chat", "--employee", "EMP001"], False, lines=["/approve", "/audit", "/quit"])
    assert text.count("unknown command") == 2


def test_chat_ends_cleanly_at_end_of_input_and_writes_nothing():
    before = data_snapshot()
    code, text = run(["chat"], False, lines=[])
    assert code == 0 and "Goodbye" in text and data_snapshot() == before
