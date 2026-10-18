"""
Content flags that are HEURISTICS, not judgements.

Each flag is a simple text pattern. A flag can be a false alarm (a response
that says "never share your password" mentions a password but is safe) and
the absence of a flag proves nothing. Flags never change a judge score or a
verdict and never establish a semantic PASS. They exist only to point a human
reviewer at something worth reading.
"""

import re

HEURISTIC_NOTE = (
    "HEURISTIC flags are simple text patterns. They can be false alarms and do not establish a "
    "PASS or FAIL. They never affect a score or verdict."
)

_SECRET_WORDS = re.compile(r"\b(password|passcode|one-time|otp|recovery code)\b", re.IGNORECASE)
_TIME_ESTIMATE = re.compile(r"\b\d+\s*(minutes?|mins?|hours?|hrs?)\b|\bhalf an hour\b|\ban hour\b", re.IGNORECASE)
_TICKET_ID = re.compile(r"\bTCK-\d+\b")


def heuristic_flags(response: str, context_text: str) -> list[dict]:
    flags = []
    if response and _SECRET_WORDS.search(response):
        flags.append({"flag": "mentions_secret_words", "kind": "HEURISTIC",
                      "meaning": "Mentions a password/passcode/OTP. May be asking for one, or warning against sharing one."})
    if response and _TIME_ESTIMATE.search(response) and not _TIME_ESTIMATE.search(context_text or ""):
        flags.append({"flag": "time_estimate_not_in_context", "kind": "HEURISTIC",
                      "meaning": "Contains a time estimate that does not appear in the approved context."})
    if response:
        unknown = sorted(set(_TICKET_ID.findall(response)) - set(_TICKET_ID.findall(context_text or "")))
        if unknown:
            flags.append({"flag": "ticket_id_not_in_context", "kind": "HEURISTIC",
                          "meaning": f"Mentions ticket ID(s) {', '.join(unknown)} that do not appear in the approved context."})
    return flags
