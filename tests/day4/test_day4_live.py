"""Day 4: live-mode behaviour, tested with fake SDK clients only (no network, no credentials)."""

import json

import pytest

from training_day4 import client as client_module
from training_day4 import data


def calls(sdk):
    return len(sdk.requests)


# ------------------------------------------------------------------ configuration

def test_judge_model_defaults_to_openai_model_and_says_so(run_cli, make_live, reports):
    live = make_live()
    run_cli("judge", "--mode", "live", "--cases", "D4-01", env=live.env, client=live.client)
    run = next(iter(reports().values()))

    assert run["models"]["generation"] == run["models"]["judge"] == "gen-model"
    assert run["models"]["same_model_for_generation_and_judging"] is True
    assert "OPENAI_JUDGE_MODEL is not set" in run["models"]["judge_model_source"]
    assert any("same model" in note for note in run["configuration_notes"])
    assert live.sdk.requests[0]["model"] == "gen-model"


def test_an_explicit_judge_model_is_used_and_recorded(run_cli, make_live, reports):
    env = {"OPENAI_API_KEY": "sk-test-not-a-real-key-123456", "OPENAI_MODEL": "gen-model", "OPENAI_JUDGE_MODEL": "judge-model"}
    live = make_live(env=env)
    run_cli("compare", "--mode", "live", "--cases", "D4-01", env=env, client=live.client)
    run = next(iter(reports().values()))

    assert run["models"]["same_model_for_generation_and_judging"] is False
    assert {r["model"] for r in live.sdk.generation_requests} == {"gen-model"}
    assert {r["model"] for r in live.sdk.judge_requests} == {"judge-model"}


def test_missing_configuration_saves_a_failed_run_and_makes_no_call(run_cli, make_live, reports):
    live = make_live(env={})  # no key, no model
    code, _, _ = run_cli("judge", "--mode", "live", "--cases", "all", env={}, client=live.client)
    run = next(iter(reports().values()))

    assert code == 1 and calls(live.sdk) == 0
    assert run["mode"] == "live" and run["status"] == "failed"
    assert {r["execution_error"]["category"] for r in run["records"]} == {"missing_configuration"}
    assert all(r["judge_assessment"]["status"] == "MISSING" for r in run["records"])
    assert not any(r["judge_assessment"]["source"] == "REPLAY" for r in run["records"])  # no silent fallback


def test_no_model_is_invented_when_openai_model_is_unset(make_live, run_cli, reports):
    env = {"OPENAI_API_KEY": "sk-test-not-a-real-key-123456", "DAY4_MODEL": "should-be-ignored"}
    live = make_live(env=env)
    run_cli("judge", "--mode", "live", "--cases", "D4-01", env=env, client=live.client)
    run = next(iter(reports().values()))

    assert calls(live.sdk) == 0 and run["models"]["generation"] is None
    assert "OPENAI_MODEL is not set" in run["records"][0]["execution_error"]["message"]


# ------------------------------------------------------------------ retries and errors

def test_transient_errors_are_retried_within_a_bound_and_every_attempt_is_kept(make_live, errors):
    outcomes = {1: errors.timeout("timed out"), 2: errors.rate("slow down")}
    live = make_live(lambda request, n: outcomes.get(n))

    result = live.client.call(model="gen-model", input_text="hello", settings={"max_output_tokens": 16})

    assert result.status == "OK" and len(result.attempts) == 3
    assert [a["outcome"] for a in result.attempts] == ["timeout", "rate_limited", "ok"]
    assert live.sleeps == [1.0, 2.0]


def test_retries_stop_at_the_maximum(make_live, errors):
    live = make_live(lambda request, n: errors.timeout("timed out"))

    result = live.client.call(model="gen-model", input_text="hello", settings={"max_output_tokens": 16})

    assert result.status == "ERROR" and calls(live.sdk) == client_module.MAX_ATTEMPTS
    assert result.error["category"] == "timeout"


def test_an_authentication_error_is_not_retried(make_live, errors):
    live = make_live(lambda request, n: errors.auth("bad key"))

    result = live.client.call(model="gen-model", input_text="hello", settings={"max_output_tokens": 16})

    assert calls(live.sdk) == 1 and result.error["category"] == "authentication"


def test_a_refusal_is_an_error_and_is_not_retried(make_live):
    from conftest import refusal_response

    live = make_live(lambda request, n: refusal_response())

    result = live.client.call(model="gen-model", input_text="hello", settings={"max_output_tokens": 16})

    assert calls(live.sdk) == 1 and result.error["category"] == "refusal"


def test_malformed_judge_output_and_low_scores_are_never_retried(run_cli, make_live, reports):
    from conftest import sdk_response

    live = make_live(lambda request, n: sdk_response("not json") if "text" in request else None)
    run_cli("judge", "--mode", "live", "--cases", "D4-01", env=live.env, client=live.client)
    record = next(iter(reports().values()))["records"][0]

    assert len(live.sdk.judge_requests) == 1
    assert record["judge_assessment"]["status"] == "ERROR" and record["judge_assessment"]["verdict"] is None
    assert record["execution_error"]["category"] == "invalid_judge_output"

    failing = make_live(judge_scores=(0, 0, 0, 0))  # a FAIL verdict must not trigger another judge call
    run_cli("judge", "--mode", "live", "--cases", "D4-02", env=failing.env, client=failing.client)
    assert len(failing.sdk.judge_requests) == 1


def test_missing_usage_is_unavailable_not_zero(make_live):
    from conftest import sdk_response

    live = make_live(lambda request, n: sdk_response("ok", usage=False))

    result = live.client.call(model="gen-model", input_text="hello", settings={"max_output_tokens": 16})

    assert result.usage == "unavailable" and result.attempts[0]["usage"] == "unavailable"


def test_credentials_and_masked_fragments_never_reach_saved_evidence(run_cli, make_live, reports, errors):
    leaky = errors.auth("Incorrect API key provided: sk-proj-" + "*" * 30 + "WXYZ and sk-test-not-a-real-key-123456")
    live = make_live(lambda request, n: leaky)
    run_cli("judge", "--mode", "live", "--cases", "D4-01", env=live.env, client=live.client)
    from training_day4 import paths

    saved = "".join(p.read_text() for p in paths.REPORTS_DIR.rglob("*") if p.is_file())

    assert "WXYZ" not in saved and "sk-test-not-a-real-key" not in saved and "sk-proj-" not in saved
    assert "[REDACTED]" in saved


def test_a_live_failure_is_never_replaced_by_replay_results(run_cli, make_live, reports, errors):
    live = make_live(lambda request, n: errors.auth("bad key"))
    code, _, _ = run_cli("compare", "--mode", "live", "--cases", "D4-01", env=live.env, client=live.client)
    run = next(iter(reports().values()))

    assert code == 1 and run["status"] == "failed" and run["mode"] == "live"
    for record in run["records"]:
        assert record["candidate_response"] is None
        assert record["generation"]["source"] == "LIVE"
        assert record["execution_error"]["category"] == "authentication"


# ------------------------------------------------------------------ compare and repeat

def test_compare_makes_sixteen_generation_and_sixteen_judge_calls_with_matching_inputs(run_cli, make_live, reports):
    live = make_live()
    run_cli("compare", "--mode", "live", "--cases", "all", "--seed", "11", env=live.env, client=live.client)
    run = next(iter(reports().values()))
    cases = data.cases_by_id(data.load_cases())

    assert len(live.sdk.generation_requests) == 16 and len(live.sdk.judge_requests) == 16
    assert run["call_counts"]["generation"]["calls_made"] == 16 and run["call_counts"]["judge"]["calls_made"] == 16
    by_case = {}
    for request in live.sdk.generation_requests:
        by_case.setdefault(request["input"], []).append(request)
    # Six distinct request+context inputs: D4-01/D4-02 and D4-06/D4-07 share theirs (the disclosed dependency),
    # so those two inputs are sent four times (two cases x two prompts) and the others twice.
    assert sorted(len(v) for v in by_case.values()) == [2, 2, 2, 2, 4, 4]
    for requests in by_case.values():
        instructions = [r["instructions"] for r in requests]
        assert len(set(instructions)) == 2 and instructions.count(instructions[0]) == len(requests) // 2  # both prompts, equally
        assert len({(r["model"], r["max_output_tokens"]) for r in requests}) == 1  # same model and settings
    # generation never sees fixed responses or answer keys
    for request in live.sdk.generation_requests:
        text = request["instructions"] + request["input"]
        for case in cases.values():
            assert case["fixed_response"] not in text
            assert not any(line in text for line in case["expected_behaviour"] + case["prohibited_behaviour"])
    # the judge sees neither prompt names nor the instructions that produced the answer
    for request in live.sdk.judge_requests:
        assert "You are an IT support assistant" not in request["input"] and "Prompt" not in request["input"]
    assert run["ordering"]["seed"] == 11 and "reproducible" in run["ordering"]["note"]


def test_the_same_seed_gives_the_same_ab_order(run_cli, make_live, reports):
    orders = []
    for _ in range(2):
        live = make_live()
        run_cli("compare", "--mode", "live", "--cases", "all", "--seed", "5", env=live.env, client=live.client)
    orders = [r["ordering"]["per_case_order"] for r in reports().values()]

    assert orders[0] == orders[1]
    assert any(order != ["A", "B"] for order in orders[0].values())  # the order really is shuffled


def test_repeat_makes_nine_generation_and_nine_judge_calls_and_keeps_every_result_and_error(run_cli, make_live, reports, errors):
    state = {"generation_calls": 0}

    def interceptor(request, n):
        if "text" not in request:
            state["generation_calls"] += 1
            if state["generation_calls"] == 4:  # one non-transient generation failure
                return errors.auth("denied")
        return None

    live = make_live(interceptor)
    run_cli("repeat", "--mode", "live", "--prompt", "B", "--cases", "D4-01", "D4-06", "D4-08", "--runs", "3", env=live.env, client=live.client)
    run = next(iter(reports().values()))
    counts = run["call_counts"]

    assert len(run["records"]) == 9  # nothing is dropped
    assert counts["generation"]["planned"] == 9 and counts["generation"]["failed"] == 1 and counts["generation"]["calls_made"] == 9
    assert counts["judge"]["planned"] == 9 and counts["judge"]["calls_made"] == 8 and counts["judge"]["not_attempted"] == 1
    assert run["status"] == "partial" and run["tally"]["evaluation_errors"] == 1
    failed = [r for r in run["records"] if r["execution_error"]]
    assert len(failed) == 1 and failed[0]["judge_assessment"]["status"] == "MISSING"


def test_a_failed_attempt_stays_visible_after_a_successful_retry(run_cli, make_live, reports, errors):
    outcomes = {1: errors.timeout("timed out")}
    live = make_live(lambda request, n: outcomes.get(n))
    run_cli("judge", "--mode", "live", "--cases", "D4-01", env=live.env, client=live.client)
    record = next(iter(reports().values()))["records"][0]

    attempts = record["judge_call"]["attempts"]
    assert [a["outcome"] for a in attempts] == ["timeout", "ok"] and record["judge_assessment"]["status"] == "EVALUATED"


def test_access_check_calls_once_for_one_model_and_twice_for_two(run_cli, make_live):
    one = make_live()
    run_cli("access-check", "--mode", "live", env=one.env, client=one.client)
    assert calls(one.sdk) == 1

    env = {"OPENAI_API_KEY": "sk-test-not-a-real-key-123456", "OPENAI_MODEL": "gen-model", "OPENAI_JUDGE_MODEL": "judge-model"}
    two = make_live(env=env)
    run_cli("access-check", "--mode", "live", env=env, client=two.client)
    assert [r["model"] for r in two.sdk.requests] == ["gen-model", "judge-model"]


def test_access_check_without_configuration_makes_no_call_and_prints_no_secret(run_cli, make_live):
    live = make_live(env={})
    code, out, err = run_cli("access-check", "--mode", "live", env={}, client=live.client)

    assert calls(live.sdk) == 0 and code == 1
    assert "sk-" not in out + err


def test_live_mode_must_be_explicit(run_cli):
    for command in (("judge", "--cases", "all"), ("compare", "--cases", "all"), ("repeat", "--prompt", "B")):
        code, _, err = run_cli(*command)
        assert code == 2 and "--mode" in err
