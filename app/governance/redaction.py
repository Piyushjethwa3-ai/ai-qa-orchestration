"""
Redaction of sensitive values (BR05).

`redact_text` removes secret values from free text; `redact` does the same recursively for dicts and
lists, and also blanks the value of any key whose NAME says it holds a secret. Both return new objects
and never change their input. Redaction errs on the side of removing too much: a false redaction costs a
little readability, a missed secret costs a leak.

This is pattern based. It catches the common shapes below. It is not a guarantee that no secret can ever
slip through (for example a password typed with no label around it), and the tests say so.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# "password is hunter2", "otp: 123456", "api key = abc" ...  keeps the label, drops the value.
_LABELLED_VALUE = re.compile(
    r"(?i)\b(pass(?:word|code|phrase)|pwd|otp|one[- ]time(?:[ -](?:code|password|passcode))?|"
    r"verification code|recovery code|2fa code|mfa code|api[ _-]?key|secret|token)\b"
    r"(\s*(?:is|=|:)\s*)([^\s,;]+)"
)
# "OTP 123456", "recovery code 99887766"  (a number straight after the label, no "is")
_LABELLED_NUMBER = re.compile(
    r"(?i)\b((?:otp|verification|recovery|2fa|mfa|security|one[- ]time)(?:\s+(?:code|password|passcode))?)\s+(\d{4,10})\b"
)
_STANDALONE = [
    re.compile(r"\bsk-[A-Za-z0-9_\-*]{8,}"),            # OpenAI-style keys, full or masked
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),         # GitHub tokens
]

_SENSITIVE_KEY_PARTS = ("password", "passcode", "passphrase", "secret", "api_key", "apikey",
                        "authorization", "credential", "recovery_code", "cookie")
_SENSITIVE_KEYS_EXACT = {"pwd", "otp", "token", "pin"}


def is_sensitive_key(key: object) -> bool:
    name = str(key).lower().replace("-", "_").replace(" ", "_")
    return (name in _SENSITIVE_KEYS_EXACT or name.endswith("_token") or name.endswith("_otp")
            or any(part in name for part in _SENSITIVE_KEY_PARTS))


def redact_text(text: str) -> str:
    """Return `text` with secret values replaced by [REDACTED]."""
    if not isinstance(text, str):
        return text
    out = _LABELLED_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    out = _LABELLED_NUMBER.sub(lambda m: f"{m.group(1)} {REDACTED}", out)
    for pattern in _STANDALONE:
        out = pattern.sub(REDACTED, out)
    return out


def contains_sensitive(text: str) -> bool:
    return isinstance(text, str) and redact_text(text) != text


def redact(value):
    """Recursively redact dicts, lists, tuples and strings. Other values are returned unchanged."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: (REDACTED if is_sensitive_key(k) and v not in (None, "") else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
