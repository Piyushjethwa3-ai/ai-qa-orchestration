"""
Where a response comes from.

- MockProvider returns a fixed, reviewed response object for each case
  (datasets/day3/mock_responses.json). Every result is labelled MOCK. A
  passing mock run proves the fixtures and workflow, not model quality.

- OpenAILiveProvider sends the rendered prompt to the OpenAI Responses
  API using Structured Outputs (a strict JSON schema). It reads
  OPENAI_API_KEY and OPENAI_MODEL from the environment and never logs the
  key. Any problem (no key, no model, SDK not installed, timeout,
  refusal, empty or incomplete output, API error) becomes status ERROR.
  It never falls back to mock responses.

Both return a ProviderResult. Neither one judges quality.
"""

import copy
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from string import Template

from day3_lab.dataset import load_json
from day3_lab.paths import MOCK_RESPONSES_PATH
from day3_lab.validation import load_response_schema

LIVE_TIMEOUT_SECONDS = 30.0
LIVE_MAX_RETRIES = 2  # passed to the SDK, which retries only connection/429/5xx-type failures

# Anything that looks like an OpenAI key, full or masked ("sk-proj-****abcd").
_KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-*]{4,}")

# Exception class name -> error category. Matching by name means this
# module does not need the openai package installed to classify errors,
# and tests can use small fake exception classes with the same names.
_ERROR_CATEGORIES = {
    "APITimeoutError": "timeout",
    "APIConnectionError": "connection",
    "AuthenticationError": "authentication",
    "PermissionDeniedError": "permission_denied",
    "RateLimitError": "rate_limited",
    "NotFoundError": "model_or_endpoint_not_found",
    "BadRequestError": "bad_request",
    "InternalServerError": "provider_server_error",
    "APIStatusError": "api_status_error",
}


@dataclass
class ProviderResult:
    mode: str  # "MOCK" or "LIVE"
    status: str  # "OK" or "ERROR"
    raw_response: str | None
    model: str | None = None
    requested_model: str | None = None
    error: dict | None = None
    token_usage: dict | None = None  # only what the provider reported; never estimated
    elapsed_ms: float | None = None
    elapsed_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def render_prompt(template_text: str, case: dict) -> str:
    """Fill the prompt template's $question and $approved_context placeholders."""
    return Template(template_text).substitute(
        question=case["question"],
        approved_context=json.dumps(case["approved_context"], indent=2, ensure_ascii=False),
    )


class MockProvider:
    mode = "MOCK"

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses

    @classmethod
    def from_file(cls, path=MOCK_RESPONSES_PATH) -> "MockProvider":
        return cls(load_json(path)["responses"])

    def respond(self, case: dict) -> ProviderResult:
        return mock_result(self.responses.get(case["case_id"]), f"no MOCK fixture for {case['case_id']}")


def mock_result(response_object: dict | None, missing_message: str) -> ProviderResult:
    """Turn a fixed response object into the raw JSON text a provider would return."""
    start = time.perf_counter()
    if response_object is None:
        return ProviderResult(
            mode="MOCK",
            status="ERROR",
            raw_response=None,
            error={"category": "missing_fixture", "message": missing_message},
        )
    raw = json.dumps(response_object, indent=2, ensure_ascii=False)
    return ProviderResult(
        mode="MOCK",
        status="OK",
        raw_response=raw,
        elapsed_ms=round((time.perf_counter() - start) * 1000, 3),
        elapsed_note="Local fixture lookup time. This is NOT model latency.",
    )


def strict_output_schema() -> dict:
    """The response schema in the form sent to OpenAI Structured Outputs.

    Strict mode needs every key in "required" and additionalProperties false,
    which our schema already has. Keywords the API may not accept in strict
    mode (minLength, pattern) and documentation-only keys are removed here.
    Local validation still applies the FULL schema to whatever comes back.
    """
    schema = copy.deepcopy(load_response_schema())
    for key in ("$schema", "title", "description"):
        schema.pop(key, None)
    for field in schema["properties"].values():
        field.pop("minLength", None)
        field.pop("pattern", None)
    return schema


def _categorise(exc: Exception) -> str:
    for cls in type(exc).__mro__:
        if cls.__name__ in _ERROR_CATEGORIES:
            return _ERROR_CATEGORIES[cls.__name__]
    return "unexpected_error"


class OpenAILiveProvider:
    mode = "LIVE"

    def __init__(
        self,
        prompt_template: str,
        env: dict | None = None,
        client_factory=None,
        timeout_seconds: float = LIVE_TIMEOUT_SECONDS,
        max_retries: int = LIVE_MAX_RETRIES,
    ):
        self.prompt_template = prompt_template
        self.env = os.environ if env is None else env
        # client_factory(api_key, timeout, max_retries) -> client. Tests pass a fake.
        self.client_factory = client_factory
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = None

    @property
    def requested_model(self) -> str | None:
        return (self.env.get("OPENAI_MODEL") or "").strip() or None

    def _error(self, category: str, message: str, raw: str | None = None, **extra) -> ProviderResult:
        return ProviderResult(
            mode="LIVE",
            status="ERROR",
            raw_response=raw,
            requested_model=self.requested_model,
            model=extra.pop("model", None),
            error={"category": category, "message": self._redact(message)},
            token_usage=extra.pop("token_usage", None),
            elapsed_ms=extra.pop("elapsed_ms", None),
            elapsed_note="Measured around the live API call." if extra.get("measured") else "",
        )

    def _redact(self, text: str) -> str:
        key = (self.env.get("OPENAI_API_KEY") or "").strip()
        text = str(text)
        if len(key) >= 8:
            text = text.replace(key, "[REDACTED]")
        # Providers echo keys back in masked form (e.g. "sk-proj-****abcd"); the
        # visible tail is still part of a secret, so remove any key-like token.
        text = _KEY_LIKE.sub("[REDACTED]", text)
        return text[:500]

    def _get_client(self, api_key: str):
        if self._client is None:
            if self.client_factory is None:
                import openai  # optional dependency: pip install -e ".[dev,live]"

                self._client = openai.OpenAI(
                    api_key=api_key, timeout=self.timeout_seconds, max_retries=self.max_retries
                )
            else:
                self._client = self.client_factory(api_key, self.timeout_seconds, self.max_retries)
        return self._client

    def respond(self, case: dict) -> ProviderResult:
        api_key = (self.env.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return self._error("missing_credentials", "OPENAI_API_KEY is not set in this terminal's environment.")
        if not self.requested_model:
            return self._error("missing_model", "OPENAI_MODEL is not set. Set it to a model your API account can use.")

        try:
            client = self._get_client(api_key)
        except ImportError:
            return self._error(
                "sdk_unavailable",
                'The openai package is not installed. Install it with: python -m pip install -e ".[dev,live]"',
            )

        start = time.perf_counter()
        try:
            response = client.responses.create(
                model=self.requested_model,
                input=render_prompt(self.prompt_template, case),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "day3_service_desk_response",
                        "schema": strict_output_schema(),
                        "strict": True,
                    }
                },
            )
        except Exception as exc:  # every SDK/network failure is recorded, never hidden
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            return self._error(_categorise(exc), f"{type(exc).__name__}: {exc}", elapsed_ms=elapsed, measured=True)
        elapsed = round((time.perf_counter() - start) * 1000, 1)

        model = getattr(response, "model", None)
        usage = _read_usage(getattr(response, "usage", None))
        common = {"model": model, "token_usage": usage, "elapsed_ms": elapsed, "measured": True}

        status = getattr(response, "status", None)
        if status not in (None, "completed"):
            details = getattr(response, "incomplete_details", None)
            return self._error("incomplete_response", f"Response status {status!r}: {details}", **common)

        texts = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                part_type = getattr(part, "type", None)
                if part_type == "refusal":
                    refusal = getattr(part, "refusal", "") or ""
                    return self._error("refusal", "The model refused to answer.", raw=refusal, **common)
                if part_type == "output_text":
                    texts.append(getattr(part, "text", "") or "")
        if not texts:
            return self._error("empty_response", "The API response contained no output text.", **common)

        return ProviderResult(
            mode="LIVE",
            status="OK",
            raw_response="".join(texts),
            model=model,
            requested_model=self.requested_model,
            token_usage=usage,
            elapsed_ms=elapsed,
            elapsed_note="Measured around the live API call, including any SDK retries.",
        )


def _read_usage(usage) -> dict | None:
    if usage is None:
        return None
    values = {
        name: getattr(usage, name, None) for name in ("input_tokens", "output_tokens", "total_tokens")
    }
    return values if any(value is not None for value in values.values()) else None
