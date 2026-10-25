"""
Loading and validating the labelled retrieval cases (datasets/day5/retrieval_cases.json).

The labels (expected and prohibited document IDs, answerable) were written from the
knowledge-base specification. They are independent of retrieval output and must not
be edited to make an evaluation pass. These checks cover shape and internal
consistency only.
"""

import json
import re
from pathlib import Path

from training_day5 import paths

REQUIRED_FIELDS = ("case_id", "query", "os", "answerable", "expected_doc_ids", "prohibited_doc_ids",
                   "expected_behaviour", "rationale")
CASE_OS_VALUES = ("macos", "windows", "any", "linux")  # linux: a deliberately unsupported OS
CASE_ID_PATTERN = re.compile(r"^R\d{2}$")


class CaseError(ValueError):
    pass


def load_cases_doc(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else Path(paths.CASES_PATH)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CaseError(f"Cannot read {paths.display(path)}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CaseError(f"{paths.display(path)} is not valid JSON ({exc})") from exc


def _id_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value) and len(set(value)) == len(value)


def inspect_cases(doc, known_ids: set[str], obsolete_ids: set[str]) -> list[str]:
    problems = []
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list) or not cases:
        return ["retrieval_cases.json must contain a non-empty 'cases' list"]
    ids = [c.get("case_id") for c in cases if isinstance(c, dict)]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"case_id {dup} appears more than once")
    for case in cases:
        if not isinstance(case, dict):
            problems.append("a case must be an object")
            continue
        cid = case.get("case_id", "?")
        missing = [f for f in REQUIRED_FIELDS if f not in case]
        if missing:
            problems.append(f"{cid}: missing field(s) {', '.join(missing)}")
            continue
        if not isinstance(cid, str) or not CASE_ID_PATTERN.match(cid):
            problems.append(f"{cid}: case_id must look like R01")
        for field in ("query", "expected_behaviour", "rationale"):
            if not isinstance(case[field], str) or not case[field].strip():
                problems.append(f"{cid}: {field} must be non-empty text")
        if case["os"] not in CASE_OS_VALUES:
            problems.append(f"{cid}: os must be one of {CASE_OS_VALUES}, found {case['os']!r}")
        if not isinstance(case["answerable"], bool):
            problems.append(f"{cid}: answerable must be true or false")
        for field in ("expected_doc_ids", "prohibited_doc_ids"):
            if not _id_list(case[field]):
                problems.append(f"{cid}: {field} must be a list of unique document IDs")
                continue
            unknown = [d for d in case[field] if d not in known_ids]
            if unknown:
                problems.append(f"{cid}: {field} names unknown document(s) {', '.join(unknown)}")
        if _id_list(case["expected_doc_ids"]) and _id_list(case["prohibited_doc_ids"]):
            both = set(case["expected_doc_ids"]) & set(case["prohibited_doc_ids"])
            if both:
                problems.append(f"{cid}: {', '.join(sorted(both))} is both expected and prohibited")
            if isinstance(case["answerable"], bool) and case["answerable"] != bool(case["expected_doc_ids"]):
                problems.append(f"{cid}: answerable must be true exactly when expected_doc_ids is non-empty")
            missing_obsolete = obsolete_ids - set(case["prohibited_doc_ids"])
            if missing_obsolete:
                problems.append(f"{cid}: every case must prohibit the obsolete document(s) {', '.join(sorted(missing_obsolete))}")
    return problems


def select_cases(doc: dict, requested: list[str]) -> list[dict]:
    """Resolve --cases. 'all' means every case in the dataset."""
    by_id = {c["case_id"]: c for c in doc["cases"]}
    if len(requested) == 1 and requested[0].lower() == "all":
        return list(doc["cases"])
    unknown = [c for c in requested if c not in by_id]
    if unknown:
        raise CaseError(f"Unknown case(s): {', '.join(unknown)}. Known cases: {', '.join(by_id)}")
    if len(set(requested)) != len(requested):
        raise CaseError("A case was listed more than once.")
    return [by_id[c] for c in requested]
