"""BR05: redaction of sensitive values."""

import copy

import pytest
from agent_support import _offline_and_isolated  # noqa: F401  (autouse offline guard)

from app.governance.redaction import REDACTED, contains_sensitive, is_sensitive_key, redact, redact_text


@pytest.mark.parametrize("text, secret", [
    ("my password is hunter2", "hunter2"),
    ("password: S3cret!pass", "S3cret!pass"),
    ("Password=abc123XYZ", "abc123XYZ"),
    ("my otp is 482913", "482913"),
    ("OTP 482913 please", "482913"),
    ("the recovery code is ABCD-EFGH-1234", "ABCD-EFGH-1234"),
    ("verification code: 99887766", "99887766"),
    ("one-time code 123456", "123456"),
    ("api key = zzz-12345", "zzz-12345"),
    ("use sk-proj-abcdefgh12345678 now", "sk-proj-abcdefgh12345678"),
    ("key sk-proj-********************ZZ99 echoed", "ZZ99"),
    ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ("token ghp_" + "a" * 30, "a" * 30),
])
def test_secret_values_are_removed(text, secret):
    out = redact_text(text)
    assert secret not in out
    assert REDACTED in out
    assert contains_sensitive(text)


@pytest.mark.parametrize("text", [
    "My VPN stopped working after I changed my password",
    "I need a password reset for my account",
    "Show me ticket TCK-1001",
    "The VPN status tool reports: operational (updated 2026-09-25T08:00:00Z).",
    "Never share passwords or OTPs.",
])
def test_harmless_text_is_unchanged(text):
    assert redact_text(text) == text
    assert not contains_sensitive(text)


def test_redaction_keeps_the_label_and_is_idempotent():
    once = redact_text("my password is hunter2")
    assert once == f"my password is {REDACTED}"
    assert redact_text(once) == once


def test_nested_structures_and_sensitive_key_names():
    original = {"user": "EMP001", "password": "hunter2", "nested": {"api_key": "abc", "ok": "fine"},
                "items": [{"token": "t0k3n"}, "my otp is 111222"], "empty_password": None, "attempt": 2}
    snapshot = copy.deepcopy(original)
    out = redact(original)
    assert out["password"] == REDACTED and out["nested"]["api_key"] == REDACTED
    assert out["items"][0]["token"] == REDACTED and "111222" not in out["items"][1]
    assert out["nested"]["ok"] == "fine" and out["user"] == "EMP001" and out["attempt"] == 2
    assert out["empty_password"] is None  # nothing to hide
    assert original == snapshot  # the input is never changed


@pytest.mark.parametrize("key, sensitive", [
    ("password", True), ("new_password", True), ("Authorization", True), ("api-key", True), ("otp", True),
    ("access_token", True), ("recovery_code", True), ("client_secret", True),
    ("idempotency_key", False), ("confirmation_id", False), ("token_usage", False), ("passed", False),
    ("employee_id", False), ("subject", False),
])
def test_sensitive_key_detection(key, sensitive):
    assert is_sensitive_key(key) is sensitive


def test_known_limit_an_unlabelled_secret_is_not_detected():
    """Redaction is pattern based. A bare secret with no label around it is NOT caught. This test records
    that limit so nobody mistakes the redactor for a guarantee."""
    assert redact_text("hunter2") == "hunter2"
