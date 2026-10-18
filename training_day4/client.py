"""
The Day 4 model adapter, for response generation and judge calls.

It uses the same supported pattern as the Day 3 live provider: the installed
`openai` SDK's Responses API, with Structured Outputs for the judge. The Day 3
provider is bound to the Day 3 prompt and schema, so Day 4 has its own adapter
and Day 3 behaviour is unchanged.

Rules this module follows:
- The model ID is always passed in by the caller from the environment. No model
  name is chosen, defaulted or substituted here.
- Retries are bounded (at most MAX_ATTEMPTS attempts per call) and only for
  transient failures: timeouts, connection errors, rate limits and 5xx errors.
  A refusal, empty or incomplete output, an authentication error or malformed
  output is never retried to get a better answer.
- Every attempt is kept (including failed ones) with its latency and usage when
  the API reported them. Missing usage is the string "unavailable", never 0.
- The API key is read from the environment at call time. It is never printed
  or stored, and error text is redacted before it is recorded.
"""

import os
import re
import time
from dataclasses import dataclass

from day3_lab.providers import _KEY_LIKE, _categorise, _read_usage

MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30.0
BACKOFF_SECONDS = (1.0, 2.0)
TRANSIENT_CATEGORIES = {"timeout", "connection", "rate_limited", "provider_server_error"}
UNAVAILABLE = "unavailable"

# Only parameters every Responses model accepts. No temperature is set, so the
# model's own sampling default applies, and the same settings go to both prompts.
GENERATION_SETTINGS = {"max_output_tokens": 400}
JUDGE_SETTINGS = {"max_output_tokens": 800}


def redact(text, env=None) -> str:
    """Remove the API key (exact, or any key-like text including masked forms) from text."""
    env = os.environ if env is None else env
    text = str(text)
    key = (env.get("OPENAI_API_KEY") or "").strip()
    if len(key) >= 8:
        text = text.replace(key, "[REDACTED]")
    return _KEY_LIKE.sub("[REDACTED]", text)


@dataclass
class CallResult:
    status: str  # "OK" or "ERROR"
    text: str | None
    model_requested: str
    model_reported: str | None
    error: dict | None
    attempts: list
    usage: object  # dict, or "unavailable"
    latency_ms: float | None  # total across all attempts

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "model_requested": self.model_requested,
            "model_reported": self.model_reported,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "attempt_count": len(self.attempts),
            "attempts": self.attempts,
            "error": self.error,
        }


class Day4Client:
    def __init__(self, env=None, client_factory=None, sleep=time.sleep, max_attempts=MAX_ATTEMPTS,
                 timeout=TIMEOUT_SECONDS):
        self.env = os.environ if env is None else env
        self.client_factory = client_factory  # (api_key, timeout, max_retries) -> client; tests pass a fake
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.timeout = timeout
        self._client = None

    def _sdk_client(self, api_key: str):
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory(api_key, self.timeout, 0)
            else:
                import openai  # installed with the 'live' extra

                # max_retries=0: this module does its own bounded retries so every attempt is recorded.
                self._client = openai.OpenAI(api_key=api_key, timeout=self.timeout, max_retries=0)
        return self._client

    def _error(self, category, message, attempts, model, started=None, usage=UNAVAILABLE, reported=None, raw=None):
        latency = round((time.perf_counter() - started) * 1000, 1) if started is not None else None
        return CallResult("ERROR", raw, model, reported, {"category": category, "message": redact(message, self.env)[:500]},
                          attempts, usage, latency)

    def call(self, *, model: str, input_text: str, settings: dict, instructions: str | None = None,
             json_schema: dict | None = None, schema_name: str | None = None) -> CallResult:
        api_key = (self.env.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return self._error("missing_credentials", "OPENAI_API_KEY is not set.", [], model)
        if not model:
            return self._error("missing_model", "No model ID was provided; none is chosen automatically.", [], model)
        try:
            client = self._sdk_client(api_key)
        except ImportError:
            return self._error("sdk_unavailable", 'The openai package is not installed. Run: python -m pip install -e ".[dev,live]"', [], model)

        request = {"model": model, "input": input_text, **settings}
        if instructions is not None:
            request["instructions"] = instructions
        if json_schema is not None:
            request["text"] = {"format": {"type": "json_schema", "name": schema_name or "day4_output",
                                          "schema": json_schema, "strict": True}}

        attempts = []
        started = time.perf_counter()
        for number in range(1, self.max_attempts + 1):
            attempt_start = time.perf_counter()
            try:
                response = client.responses.create(**request)
            except Exception as exc:  # every SDK/network failure is recorded
                category = _categorise(exc)
                if category == "rate_limited" and "insufficient_quota" in str(exc):
                    category = "quota_exhausted"  # retrying cannot help
                retryable = category in TRANSIENT_CATEGORIES
                attempts.append({"attempt": number, "outcome": category, "retryable": retryable,
                                 "latency_ms": round((time.perf_counter() - attempt_start) * 1000, 1),
                                 "usage": UNAVAILABLE, "message": redact(f"{type(exc).__name__}: {exc}", self.env)[:300]})
                if retryable and number < self.max_attempts:
                    self.sleep(BACKOFF_SECONDS[min(number - 1, len(BACKOFF_SECONDS) - 1)])
                    continue
                return self._error(category, f"{type(exc).__name__}: {exc}", attempts, model, started)
            latency = round((time.perf_counter() - attempt_start) * 1000, 1)
            usage = _read_usage(getattr(response, "usage", None)) or UNAVAILABLE
            reported = getattr(response, "model", None)
            outcome, text = self._read_output(response)
            attempts.append({"attempt": number, "outcome": "ok" if outcome is None else outcome["category"],
                             "retryable": False, "latency_ms": latency, "usage": usage,
                             "message": None if outcome is None else redact(outcome["message"], self.env)[:300]})
            if outcome is not None:  # refusal / empty / incomplete: never retried
                return self._error(outcome["category"], outcome["message"], attempts, model, started,
                                   usage=usage, reported=reported, raw=outcome.get("raw"))
            total = round((time.perf_counter() - started) * 1000, 1)
            return CallResult("OK", text, model, reported, None, attempts, usage, total)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _read_output(response):
        """Return (error_or_None, text)."""
        status = getattr(response, "status", None)
        if status not in (None, "completed"):
            return {"category": "incomplete_response", "message": f"Response status {status!r}."}, None
        texts = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                kind = getattr(part, "type", None)
                if kind == "refusal":
                    return {"category": "refusal", "message": "The model refused to answer.",
                            "raw": getattr(part, "refusal", "") or ""}, None
                if kind == "output_text":
                    texts.append(getattr(part, "text", "") or "")
        if not texts or not "".join(texts).strip():
            return {"category": "empty_response", "message": "The API response contained no output text."}, None
        return None, "".join(texts)
