"""
Confirmed human reviews, kept apart from proposals and from judge output.

A proposed label (datasets/day4/human_labels.json) is a suggestion. It becomes
a HUMAN ASSESSMENT only when a named reviewer records one here, by running a
review command with their own identity. Reviews are:

- append-only: a newer review for the same target supersedes an earlier one but
  never deletes it, and original run evidence is never rewritten;
- bound to fingerprints (hashes) of the request, approved context, response and
  rubric they judged, so a change to any of them makes the review STALE;
- scored by the reviewer; the total and verdict are computed in code.

Nothing in this module reads a judge score, and nothing copies a proposed label
unless the reviewer explicitly asks to confirm it (basis "confirmed_proposed_label").
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from training_day4 import rules

# Obvious placeholders that must not be recorded as a real reviewer identity.
PLACEHOLDER_REVIEWERS = {
    "", "name", "your name", "<your name>", "reviewer", "trainer", "me", "user", "student", "test", "tbd",
    "claude", "assistant", "ai", "llm", "model", "judge", "gpt", "none", "n/a",
}


class ReviewError(ValueError):
    """A review was refused. The message says why."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_reviewer(name) -> str:
    if not isinstance(name, str) or name.strip().lower() in PLACEHOLDER_REVIEWERS or len(name.strip()) < 2:
        raise ReviewError("A real reviewer identity is required (your own name). Placeholders are refused.")
    return name.strip()


def build_review(*, target: dict, scores: dict, critical, reason: str, reviewer: str, basis: str,
                 bound_to: dict, previous_id: str | None = None) -> dict:
    if sorted(scores) != sorted(rules.DIMENSIONS):
        raise ReviewError(f"Scores are required for exactly: {', '.join(rules.DIMENSIONS)}.")
    for dimension in rules.DIMENSIONS:
        value = scores[dimension]
        if type(value) is not int or value not in (0, 1, 2):  # rejects True, 2.0, "2"
            raise ReviewError(f"{dimension} score must be the integer 0, 1 or 2, got {value!r}.")
    critical = list(critical)
    for item in critical:
        if item not in rules.CRITICAL_CATEGORIES:
            raise ReviewError(f"{item!r} is not a critical category. Allowed: {', '.join(rules.CRITICAL_CATEGORIES)}.")
    if len(set(critical)) != len(critical):
        raise ReviewError("A critical category was listed more than once.")
    if not isinstance(reason, str) or not reason.strip():
        raise ReviewError("A non-empty reason is required.")
    return {
        "review_id": "HR-" + uuid.uuid4().hex[:10],
        "target": target,
        "human_confirmed": True,
        "scores": dict(scores),
        "total": rules.total_score(scores),
        "critical_violations": critical,
        "verdict": rules.verdict_from_scores(scores, critical),
        "reason": reason.strip(),
        "reviewer": validate_reviewer(reviewer),
        "reviewed_at": utc_now(),
        "basis": basis,
        "bound_to": bound_to,
        "supersedes": previous_id,
        "verdict_note": "Total and verdict are computed in code from the reviewer's scores and critical violations.",
    }


def stale_fields(review: dict, expected_bound: dict) -> list[str]:
    """Names of the fingerprints that no longer match what the review judged."""
    return [key for key, value in expected_bound.items() if review.get("bound_to", {}).get(key) != value]


def load_doc(path: Path, default: dict) -> dict:
    if not Path(path).exists():
        return json.loads(json.dumps(default))
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_doc(path: Path, doc: dict) -> None:
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    os.replace(temp, path)  # atomic: readers never see a half-written file


def current_reviews(doc: dict, key: str) -> dict[str, dict]:
    """Latest review per target (key is 'case_id' or 'response_id')."""
    latest: dict[str, dict] = {}
    for review in doc.get("reviews", []):  # file order is chronological
        latest[review["target"][key]] = review
    return latest


def append_review(path: Path, default: dict, review: dict, key: str) -> dict:
    doc = load_doc(path, default)
    previous = current_reviews(doc, key).get(review["target"][key])
    review["supersedes"] = previous["review_id"] if previous else None
    doc["reviews"].append(review)
    save_doc(path, doc)
    return review
