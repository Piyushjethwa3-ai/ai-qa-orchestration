"""
Day 4 test fixtures. Every Day 4 test runs offline and isolated:

- OPENAI_API_KEY, OPENAI_MODEL, OPENAI_JUDGE_MODEL and DAY4_MODEL are removed for
  each test, so a configured terminal can never trigger a paid call.
- Opening a network connection raises an error, so an accidental live call fails
  loudly instead of reaching the internet.
- Reports are written to a temporary folder, and human reviews of the fixed
  responses go to a temporary copy, so tests never touch reports/day4 or
  datasets/day4/human_reviews.json.
- SDK behaviour is simulated with fake clients; nothing here imports a network
  library call path.

This file is a separate copy of the Day 3 protection (tests/day3/conftest.py) on
purpose: the Day 3 guard is unchanged and Day 1-3 tests are not affected.
"""

import json
import re
import socket
from types import SimpleNamespace

import pytest

from training_day4 import cli, client as client_module, paths

from day4_support import refusal_response, sdk_response  # noqa: F401  (FakeSDK uses sdk_response)

KEY = "sk-test-not-a-real-key-123456"
LIVE_ENV = {"OPENAI_API_KEY": KEY, "OPENAI_MODEL": "gen-model"}


@pytest.fixture(autouse=True)
def _offline_and_isolated(monkeypatch, tmp_path):
    for variable in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_JUDGE_MODEL", "DAY4_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    def _blocked(*args, **kwargs):
        raise RuntimeError("Network access is disabled in Day 4 tests.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    monkeypatch.setattr(paths, "REPORTS_DIR", tmp_path / "reports_day4")
    reviews_copy = tmp_path / "human_reviews.json"
    reviews_copy.write_text(json.dumps({"reviews_version": "day4-v1", "reviews": []}), encoding="utf-8")
    monkeypatch.setattr(paths, "REVIEWS_PATH", reviews_copy)


@pytest.fixture()
def run_cli(capsys):
    """Run `python -m training_day4 ...` in-process. Returns (exit_code, stdout, stderr)."""

    def _run(*args, env=None, client=None, sleep=None):
        try:
            code = cli.main([str(a) for a in args], env=env, client=client, sleep=sleep)
        except SystemExit as exc:  # argparse rejects bad arguments this way
            code = exc.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture()
def reports():
    """Load every finalised-or-not run.json in the temporary reports folder, keyed by folder name."""

    def _load():
        out = {}
        if paths.REPORTS_DIR.exists():
            for folder in sorted(paths.REPORTS_DIR.iterdir()):
                out[folder.name] = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        return out

    return _load


# ---------------------------------------------------------------- fake SDK

def judge_json(request, scores=(2, 2, 2, 2), critical=()):
    response_id = re.search(r"Response ID \(copy it back exactly\): (R-[0-9a-f]{8})", request["input"]).group(1)
    names = ("correctness", "relevance", "completeness", "safety_and_policy")
    return json.dumps({"response_id": response_id, "scores": dict(zip(names, scores)), "critical_violations": list(critical),
                       "reasons": {n: f"Reason for {n}." for n in names}})


class FakeSDK:
    """Stands in for the OpenAI client. `interceptor(request, call_number)` may return a
    response, raise an exception, or return None to use the default behaviour."""

    def __init__(self, interceptor=None, judge_scores=(2, 2, 2, 2), judge_critical=()):
        self.interceptor = interceptor
        self.judge_scores, self.judge_critical = judge_scores, judge_critical
        self.requests = []
        self.responses = self

    @property
    def generation_requests(self):
        return [r for r in self.requests if "text" not in r and r["input"] != "Reply with the single word OK."]

    @property
    def judge_requests(self):
        return [r for r in self.requests if "text" in r]

    def create(self, **request):
        self.requests.append(request)
        if self.interceptor is not None:
            outcome = self.interceptor(request, len(self.requests))
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
        if "text" in request:
            return sdk_response(judge_json(request, self.judge_scores, self.judge_critical))
        return sdk_response("Please check the service-status page.")


@pytest.fixture()
def make_live():
    """Build (client, sdk, sleeps) wired to a FakeSDK. Pass env=... to change the configuration."""

    def _make(interceptor=None, env=None, **sdk_kwargs):
        sdk = FakeSDK(interceptor, **sdk_kwargs)
        sleeps = []
        env = dict(LIVE_ENV) if env is None else env
        client = client_module.Day4Client(env=env, client_factory=lambda key, timeout, retries: sdk, sleep=sleeps.append)
        return SimpleNamespace(client=client, sdk=sdk, sleeps=sleeps, env=env)

    return _make


# Fake exception classes named like the SDK's, so errors are classified by name.
class APITimeoutError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class RateLimitError(Exception):
    pass


@pytest.fixture()
def errors():
    return SimpleNamespace(timeout=APITimeoutError, auth=AuthenticationError, rate=RateLimitError)
