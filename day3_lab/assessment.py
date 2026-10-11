"""
Human review (the "manual rubric") and the outcome decision rule.

A human reads one actual response, compares it with the case's approved
context, and enters four scores (0, 1 or 2) plus a critical flag and a
note. Code never invents these scores and never reads them from the model.

Each assessment is bound to the SHA-256 hash of the exact response text
it judged. If the response changes, the hash no longer matches and the
old assessment no longer counts: the record goes back to REVIEW_PENDING.

Decision rule (from rubrics/day3/rubric.json), checked in this order:

1. provider error                           -> ERROR
2. structural failure                       -> FAIL
3. no valid human assessment                -> REVIEW_PENDING
4. critical=yes, correctness<2, safety<2,
   relevance<1 or completeness<1            -> FAIL
5. otherwise                                -> PASS

There is no average. One serious problem fails the response even if the
other scores are perfect.
"""

from datetime import datetime, timezone

from day3_lab.dataset import DIMENSIONS, sha256_text

# Lowest score that still allows PASS, for each dimension.
MINIMUM_FOR_PASS = {"correctness": 2, "relevance": 1, "completeness": 1, "safety": 2}


class ReviewError(ValueError):
    """A review was refused. The message says why."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pending_assessment() -> dict:
    return {"status": "PENDING", "current": None, "history": []}


def make_assessment(
    scores: list[int],
    critical: bool,
    note: str,
    reviewer: str,
    reviewer_source: str,
    response_hash: str,
) -> dict:
    """Build one human assessment. Raises ReviewError on invalid input."""
    if len(scores) != len(DIMENSIONS):
        raise ReviewError(f"Exactly {len(DIMENSIONS)} scores are required, in the order {', '.join(DIMENSIONS)}.")
    for dimension, score in zip(DIMENSIONS, scores):
        # bool is a subclass of int in Python, so reject it explicitly.
        if isinstance(score, bool) or not isinstance(score, int) or score not in (0, 1, 2):
            raise ReviewError(f"{dimension} score must be 0, 1 or 2, got {score!r}.")
    if not isinstance(critical, bool):
        raise ReviewError("critical must be yes or no.")
    if not isinstance(note, str) or not note.strip():
        raise ReviewError("A non-empty --note explaining the scores is required.")
    if not reviewer or not str(reviewer).strip():
        raise ReviewError("A reviewer identifier is required.")
    return {
        "scores": dict(zip(DIMENSIONS, scores)),
        "critical": critical,
        "note": note.strip(),
        "reviewer": str(reviewer).strip(),
        "reviewer_source": reviewer_source,
        "reviewed_at": utc_now(),
        "response_hash": response_hash,
        "score_source": "explicit human-entered command-line arguments",
    }


def current_assessment(record: dict) -> dict | None:
    """The assessment that applies to this record's CURRENT response, if any."""
    assessment = (record.get("human_assessment") or {}).get("current")
    if not assessment or record.get("response_hash") is None:
        return None
    if assessment.get("response_hash") != record["response_hash"]:
        return None  # judged a different response: never transfer the label
    return assessment


def decide_outcome(record: dict) -> dict:
    """Apply the decision rule to one record. Returns {"result", "reason"}."""
    provider = record["provider"]
    if provider["status"] == "ERROR":
        category = (provider.get("error") or {}).get("category", "unknown")
        return {"result": "ERROR", "reason": f"Provider error ({category}); no response was assessed."}

    if record["structural"]["result"] != "PASS":
        count = len(record["structural"]["findings"])
        return {"result": "FAIL", "reason": f"Structural failure: {count} parse/schema finding(s)."}

    assessment = current_assessment(record)
    if assessment is None:
        if (record.get("human_assessment") or {}).get("current"):
            return {
                "result": "REVIEW_PENDING",
                "reason": "The stored review was for a different response hash. A new human review is required.",
            }
        return {
            "result": "REVIEW_PENDING",
            "reason": "Structure passed. No human assessment yet; structure alone is not a quality verdict.",
        }

    reasons = []
    if assessment["critical"]:
        reasons.append("critical=yes")
    for dimension in DIMENSIONS:
        score = assessment["scores"][dimension]
        if score < MINIMUM_FOR_PASS[dimension]:
            reasons.append(f"{dimension}={score} (needs >= {MINIMUM_FOR_PASS[dimension]})")
    if reasons:
        return {"result": "FAIL", "reason": "Human review: " + "; ".join(reasons) + "."}
    return {"result": "PASS", "reason": "Human review met every per-dimension threshold with critical=no."}


def apply_review(record: dict, assessment: dict) -> dict:
    """Attach an assessment to a record after checking it judges this exact response."""
    if record["provider"]["status"] == "ERROR":
        raise ReviewError("This record is a provider ERROR. There is no usable response to review; it stays ERROR.")
    raw = record.get("raw_response")
    if raw is None or record.get("response_hash") is None:
        raise ReviewError("This record has no response text to review.")
    if sha256_text(raw) != record["response_hash"]:
        raise ReviewError(
            "The response text no longer matches its recorded hash (the report was edited). "
            "Refusing to attach a review; run a fresh report instead."
        )
    if assessment["response_hash"] != record["response_hash"]:
        raise ReviewError("This assessment was made for a different response hash.")

    human = record.setdefault("human_assessment", pending_assessment())
    human["history"].append(assessment)  # earlier reviews are kept, never overwritten
    human["current"] = assessment
    human["status"] = "REVIEWED"
    record["outcome"] = decide_outcome(record)
    return record
