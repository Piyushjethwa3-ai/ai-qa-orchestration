"""Loading the Day 4 inputs. Plain functions that read JSON files into dictionaries and lists."""

import hashlib
import json
from pathlib import Path

from training_day4 import paths

SPLITS = {
    "development": ["D4-01", "D4-02", "D4-03", "D4-04"],
    "holdout": ["D4-05", "D4-06", "D4-07", "D4-08"],
}
ALL_CASE_IDS = SPLITS["development"] + SPLITS["holdout"]


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_cases() -> dict:
    return load_json(paths.CASES_PATH)


def cases_by_id(doc: dict) -> dict[str, dict]:
    return {case["case_id"]: case for case in doc["cases"]}


def load_labels() -> dict:
    return load_json(paths.LABELS_PATH)


def labels_by_id(doc: dict) -> dict[str, dict]:
    return {label["case_id"]: label for label in doc["labels"]}


def load_rubric() -> dict:
    return load_json(paths.RUBRIC_PATH)


def load_replay() -> dict:
    return load_json(paths.REPLAY_PATH)


def select_cases(requested: list[str], dataset: dict) -> list[dict]:
    """Resolve --cases. 'all' means every case in the dataset (the eight supplied cases)."""
    known = cases_by_id(dataset)
    if len(requested) == 1 and requested[0].lower() == "all":
        return list(dataset["cases"])
    unknown = [case_id for case_id in requested if case_id not in known]
    if unknown:
        raise ValueError(f"Unknown case(s): {', '.join(unknown)}. Known cases: {', '.join(known)}")
    if len(set(requested)) != len(requested):
        raise ValueError("A case was listed more than once.")
    return [known[case_id] for case_id in requested]


def shared_input_groups(dataset: dict) -> dict[str, list[str]]:
    """Cases that share the same request AND approved context (their results are not independent)."""
    groups: dict[str, list[str]] = {}
    for case in dataset["cases"]:
        key = sha256_text(case["user_input"] + "\n" + case["approved_context"])
        groups.setdefault(key, []).append(case["case_id"])
    return {key[:8]: ids for key, ids in groups.items() if len(ids) > 1}


def dependency_note(dataset: dict) -> str:
    groups = shared_input_groups(dataset).values()
    if not groups:
        return "No cases share a request and context."
    pairs = "; ".join(" and ".join(ids) for ids in groups)
    return (f"Dependence: {pairs} share the same request and approved context, so their results are not "
            "independent observations. Eight examples are a workflow demonstration, not a reliability measure.")


def case_binding(case: dict, rubric_sha256: str, rubric_version: str) -> dict:
    """Fingerprints that a human review is bound to. If any changes, the review is stale."""
    return {
        "case_id": case["case_id"],
        "user_input_sha256": sha256_text(case["user_input"]),
        "approved_context_sha256": sha256_text(case["approved_context"]),
        "response_sha256": sha256_text(case["fixed_response"]),
        "rubric_version": rubric_version,
        "rubric_sha256": rubric_sha256,
    }
