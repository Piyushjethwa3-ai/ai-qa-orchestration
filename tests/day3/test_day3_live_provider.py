"""
Day 3: the live OpenAI adapter, tested with FAKE clients only.

No test here touches the network or needs the openai package. Each fake
mimics the shape of an SDK response or raises an exception with the same
class name as the SDK's error. The point: every failure is recorded as
ERROR, and a live failure never becomes a mock pass.
"""

import json
from types import SimpleNamespace

import pytest

from day3_lab import paths
from day3_lab.dataset import load_cases, load_json
from day3_lab.providers import OpenAILiveProvider
from day3_lab.runner import build_record, run_cases

ENV = {"OPENAI_API_KEY": "sk-test-not-a-real-key-123456", "OPENAI_MODEL": "test-model-id"}
CASE = load_cases()["cases"][0]
MOCK_RAW_ANSWER = load_json(paths.MOCK_RESPONSES_PATH)["responses"]["D3-01"]["answer"]
GOOD = {
    "answer": "Live answer: outage confirmed, no ETA.",
    "service_status": "outage",
    "recovery_time": None,
    "next_step": "Watch status updates.",
}


# Fake exception classes named like the SDK's, so classification is by name.
class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


def _sdk_response(parts, status="completed", usage=True):
    return SimpleNamespace(
        model="test-model-id-2026",
        status=status,
        incomplete_details=None,
        output=[SimpleNamespace(type="message", content=parts)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=40, total_tokens=160) if usage else None,
    )


def _text(text):
    return SimpleNamespace(type="output_text", text=text)


class FakeClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _provider(outcome, env=ENV):
    client = FakeClient(outcome)
    provider = OpenAILiveProvider("Q: $question\nC: $approved_context", env=env,
                                  client_factory=lambda key, timeout, retries: client)
    return provider, client


def _record(outcome, env=ENV):
    provider, client = _provider(outcome, env)
    return build_record(CASE["case_id"], CASE, provider.respond(CASE)), client


def _assert_error_not_mock_pass(record, category):
    assert record["source"] == "LIVE"
    assert record["provider"]["status"] == "ERROR"
    assert record["provider"]["error"]["category"] == category
    assert record["outcome"]["result"] == "ERROR"
    assert MOCK_RAW_ANSWER not in (record["raw_response"] or "")  # never substituted with mock


def test_valid_live_response_is_structurally_checked_and_pending():
    record, client = _record(_sdk_response([_text(json.dumps(GOOD))]))

    assert record["provider"]["status"] == "OK"
    assert record["provider"]["model"] == "test-model-id-2026"
    assert record["provider"]["token_usage"] == {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}
    assert record["outcome"]["result"] == "REVIEW_PENDING"  # live answers need human review too
    request = client.calls[0]
    assert request["model"] == "test-model-id"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert CASE["question"] in request["input"]


def test_missing_usage_is_recorded_as_null_not_invented():
    record, _ = _record(_sdk_response([_text(json.dumps(GOOD))], usage=False))

    assert record["provider"]["token_usage"] is None


def test_missing_api_key_is_error_and_makes_no_call():
    record, client = _record(_sdk_response([_text(json.dumps(GOOD))]), env={"OPENAI_MODEL": "m"})

    _assert_error_not_mock_pass(record, "missing_credentials")
    assert client.calls == []


def test_missing_model_is_error_and_makes_no_call():
    record, client = _record(_sdk_response([]), env={"OPENAI_API_KEY": ENV["OPENAI_API_KEY"]})

    _assert_error_not_mock_pass(record, "missing_model")
    assert client.calls == []


@pytest.mark.parametrize(
    "exc, category",
    [
        pytest.param(APITimeoutError("Request timed out."), "timeout", id="timeout"),
        pytest.param(APIConnectionError("Connection error."), "connection", id="connection"),
        pytest.param(AuthenticationError("Invalid API key"), "authentication", id="auth"),
        pytest.param(RateLimitError("Too many requests"), "rate_limited", id="rate_limit"),
        pytest.param(ValueError("something odd"), "unexpected_error", id="unexpected"),
    ],
)
def test_api_failures_become_error_never_mock_pass(exc, category):
    record, _ = _record(exc)

    _assert_error_not_mock_pass(record, category)
    assert record["raw_response"] is None


def test_refusal_is_error_and_refusal_text_is_kept_as_evidence():
    refusal = SimpleNamespace(type="refusal", refusal="I can't help with that.")
    record, _ = _record(_sdk_response([refusal]))

    _assert_error_not_mock_pass(record, "refusal")
    assert record["raw_response"] == "I can't help with that."


def test_malformed_live_output_is_error_with_findings_kept():
    record, _ = _record(_sdk_response([_text('{"answer": "fixed in 30 minutes"}')]))

    _assert_error_not_mock_pass(record, "malformed_response")
    assert record["structural"]["result"] == "FAIL"
    assert record["structural"]["findings"]
    assert record["raw_response"] == '{"answer": "fixed in 30 minutes"}'


def test_incomplete_response_is_error():
    record, _ = _record(_sdk_response([_text("{")], status="incomplete"))

    _assert_error_not_mock_pass(record, "incomplete_response")


def test_empty_output_is_error():
    record, _ = _record(_sdk_response([]))

    _assert_error_not_mock_pass(record, "empty_response")


def test_api_key_is_redacted_from_error_messages():
    record, _ = _record(AuthenticationError(f"Incorrect API key provided: {ENV['OPENAI_API_KEY']}"))

    assert ENV["OPENAI_API_KEY"] not in json.dumps(record)
    assert "[REDACTED]" in record["provider"]["error"]["message"]


def test_live_run_records_requested_model_and_no_fallback():
    provider, _ = _provider(APITimeoutError("Request timed out."))

    run = run_cases("live", case_id="D3-01", provider=provider)

    assert run["provider_mode"] == "LIVE"
    assert run["requested_model"] == "test-model-id"
    assert run["live_adapter"]["fallback_to_mock"] is False
    assert run["summary"]["outcome"] == {"ERROR": 1}


def test_live_cli_without_credentials_saves_error_report(tmp_path, run_cli, read_json):
    # conftest removes OPENAI_API_KEY, so this exercises the real CLI path with no network.
    code, out, _ = run_cli("run", "--mode", "live", "--case", "D3-01", "--out", tmp_path / "live")
    run = read_json(tmp_path / "live" / "run.json")

    assert code == 1
    assert run["provider_mode"] == "LIVE"
    assert run["records"][0]["outcome"]["result"] == "ERROR"
    assert run["records"][0]["provider"]["error"]["category"] == "missing_credentials"
    assert "PASS" not in run["summary"]["outcome"]


def test_missing_sdk_is_error_not_mock(monkeypatch):
    # Setting sys.modules["openai"] to None makes `import openai` raise ImportError.
    monkeypatch.setitem(__import__("sys").modules, "openai", None)
    provider = OpenAILiveProvider("Q: $question\nC: $approved_context", env=ENV)

    record = build_record(CASE["case_id"], CASE, provider.respond(CASE))

    _assert_error_not_mock_pass(record, "sdk_unavailable")


def test_masked_key_echoed_by_provider_is_redacted():
    # OpenAI's 401 message echoes a masked key with its last 4 characters visible.
    masked = "sk-proj-" + "*" * 40 + "JQsA"
    record, _ = _record(AuthenticationError(f"Error code: 401 - Incorrect API key provided: {masked}. See docs."))

    saved = json.dumps(record)
    assert "JQsA" not in saved and masked not in saved
    assert record["provider"]["error"]["category"] == "authentication"
    assert "Incorrect API key provided: [REDACTED]" in record["provider"]["error"]["message"]
