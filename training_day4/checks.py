"""
The `validate` command: structural checks on every Day 4 input.

These checks look at SHAPE and consistency only. They cannot tell you whether a
case's approved context is right or whether a proposed label is a fair judgement.
Unconfirmed proposed labels are an expected readiness gap, reported as a warning,
not as malformed data.
"""

import json
import re

from training_day4 import data, judge, paths, reviews, rules

REQUIRED_CASE_KEYS = (
    "case_id", "requirement_ids", "split", "user_input", "approved_context", "expected_behaviour",
    "prohibited_behaviour", "fixed_response", "expected_critical_violations",
)
REQUIRED_PLACEHOLDERS = ("$response_id", "$rubric", "$critical_categories", "$employee_request",
                         "$approved_context", "$candidate_response")
FORBIDDEN_IN_JUDGE_TEMPLATE = ("expected_behaviour", "prohibited_behaviour", "expected_critical", "human_label",
                               "proposed", "case_id", "Prompt A", "Prompt B")


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value, allow_empty: bool) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(_text(v) for v in value)


def defined_business_rules() -> set[str]:
    if not paths.BUSINESS_RULES_PATH.exists():
        return set()
    return set(re.findall(r"^## (BR\d{2})\b", paths.BUSINESS_RULES_PATH.read_text(encoding="utf-8"), flags=re.MULTILINE))


def check_rubric(rubric: dict) -> list[str]:
    problems = []
    if not _text(rubric.get("version")):
        problems.append("rubric.json: 'version' is required.")
    if rubric.get("dimension_order") != list(rules.DIMENSIONS):
        problems.append(f"rubric.json: dimension_order must be {list(rules.DIMENSIONS)}.")
    for dimension in rules.DIMENSIONS:
        scale = rubric.get("scales", {}).get(dimension)
        if not isinstance(scale, dict) or sorted(scale) != ["0", "1", "2"] or not all(_text(v) for v in scale.values()):
            problems.append(f"rubric.json: scale for {dimension} must describe exactly 0, 1 and 2.")
    if sorted(rubric.get("critical_categories", {})) != sorted(rules.CRITICAL_CATEGORIES):
        problems.append(f"rubric.json: critical_categories must be exactly {list(rules.CRITICAL_CATEGORIES)}.")
    if rubric.get("pass_thresholds") != rules.PASS_THRESHOLDS:
        problems.append("rubric.json: pass_thresholds differ from the thresholds computed in rules.py.")
    return problems


def check_cases(doc: dict, defined_rules: set[str]) -> list[str]:
    problems = []
    cases = doc.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["cases.json: 'cases' must be a non-empty list."]
    ids = [c.get("case_id") for c in cases]
    for case_id in sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1}):
        problems.append(f"cases.json: case_id {case_id} appears more than once.")
    if sorted(i for i in ids if isinstance(i, str)) != sorted(data.ALL_CASE_IDS):
        problems.append(f"cases.json: expected exactly the cases {data.ALL_CASE_IDS}, found {ids}.")
    for case in cases:
        cid = case.get("case_id", "?")
        missing = [key for key in REQUIRED_CASE_KEYS if key not in case]
        for key in missing:
            problems.append(f"{cid}: missing key '{key}'.")
        if missing:
            continue
        expected_split = next((s for s, members in data.SPLITS.items() if cid in members), None)
        if case["split"] != expected_split:
            problems.append(f"{cid}: split must be '{expected_split}', found {case['split']!r}.")
        if not _text_list(case["requirement_ids"], allow_empty=False):
            problems.append(f"{cid}: requirement_ids must be a non-empty list of strings.")
        else:
            for rid in case["requirement_ids"]:
                if rid not in defined_rules:
                    problems.append(f"{cid}: {rid} is not defined in docs/business_rules.md.")
        for key in ("user_input", "approved_context", "fixed_response"):
            if not _text(case[key]):
                problems.append(f"{cid}: '{key}' must be non-empty text.")
        for key in ("expected_behaviour", "prohibited_behaviour"):
            if not _text_list(case[key], allow_empty=False):
                problems.append(f"{cid}: '{key}' must be a non-empty list of strings.")
        critical = case["expected_critical_violations"]
        if not isinstance(critical, list) or any(c not in rules.CRITICAL_CATEGORIES for c in critical):
            problems.append(f"{cid}: expected_critical_violations must be a list of allowed critical categories.")
    return problems


def check_label_shape(scores, critical) -> bool:
    return (isinstance(scores, dict) and sorted(scores) == sorted(rules.DIMENSIONS)
            and all(type(v) is int and v in (0, 1, 2) for v in scores.values())
            and isinstance(critical, list) and all(c in rules.CRITICAL_CATEGORIES for c in critical))


def check_labels(doc: dict, case_ids: list[str]) -> list[str]:
    problems = []
    labels = doc.get("labels")
    if not isinstance(labels, list):
        return ["human_labels.json: 'labels' must be a list."]
    seen = [label.get("case_id") for label in labels]
    for case_id in case_ids:
        if seen.count(case_id) != 1:
            problems.append(f"human_labels.json: expected exactly one proposed label for {case_id}, found {seen.count(case_id)}.")
    for extra in sorted(set(seen) - set(case_ids)):
        problems.append(f"human_labels.json: label for unknown case {extra}.")
    for label in labels:
        cid = label.get("case_id", "?")
        if label.get("label_source") != "trainer_proposed" or label.get("human_confirmed") is not False:
            problems.append(f"{cid}: this file may only hold trainer_proposed labels with human_confirmed false. "
                            "Confirmed reviews belong in human_reviews.json.")
        if not check_label_shape(label.get("scores"), label.get("critical_violations")):
            problems.append(f"{cid}: label scores must be integers 0-2 for {list(rules.DIMENSIONS)} and critical violations must be allowed categories.")
            continue
        expected = rules.verdict_from_scores(label["scores"], label["critical_violations"])
        if label.get("verdict") != expected:
            problems.append(f"{cid}: proposed verdict {label.get('verdict')!r} does not follow from its scores and critical violations (rule gives {expected}).")
        if not _text(label.get("reason")):
            problems.append(f"{cid}: label needs a reason.")
    return problems


def check_replay(doc: dict, case_ids: list[str]) -> list[str]:
    problems = []

    def check_output(where, output):
        _, findings = judge.validate_judge_output(json.dumps({"response_id": "R-check", **output}), "R-check")
        if findings:
            problems.append(f"replay_fixtures.json {where}: judge output is invalid ({findings[0]['message']}).")

    for case_id in case_ids:
        if case_id not in doc.get("judge_fixed", {}):
            problems.append(f"replay_fixtures.json: no judge_fixed entry for {case_id}.")
        else:
            check_output(f"judge_fixed/{case_id}", doc["judge_fixed"][case_id])
        for prompt in ("A", "B"):
            entry = doc.get("compare", {}).get(case_id, {}).get(prompt)
            if not entry or not _text(entry.get("response")):
                problems.append(f"replay_fixtures.json: no compare fixture for {case_id}/{prompt}.")
            else:
                check_output(f"compare/{case_id}/{prompt}", entry["judge_output"])
    for prompt, by_case in doc.get("repeat", {}).items():
        for case_id, runs in by_case.items():
            for index, entry in enumerate(runs, start=1):
                check_output(f"repeat/{prompt}/{case_id}/run{index}", entry["judge_output"])
    return problems


def check_reviews(doc: dict, cases: dict[str, dict]) -> list[str]:
    problems = []
    if not isinstance(doc.get("reviews"), list):
        return ["human_reviews.json: 'reviews' must be a list."]
    for review in doc["reviews"]:
        rid = review.get("review_id", "?")
        try:
            reviews.build_review(target=review["target"], scores=review["scores"], critical=review["critical_violations"],
                                 reason=review["reason"], reviewer=review["reviewer"], basis=review.get("basis", ""),
                                 bound_to=review.get("bound_to", {}))
        except (ReviewErrorTypes, KeyError, TypeError) as exc:
            problems.append(f"human_reviews.json {rid}: invalid review ({exc}).")
            continue
        if review.get("verdict") != rules.verdict_from_scores(review["scores"], review["critical_violations"]):
            problems.append(f"human_reviews.json {rid}: verdict does not follow from the scores.")
        if review["target"].get("case_id") not in cases:
            problems.append(f"human_reviews.json {rid}: unknown case {review['target'].get('case_id')}.")
    return problems


ReviewErrorTypes = reviews.ReviewError


def review_status(cases_doc: dict, rubric_sha: str, rubric_version: str) -> dict:
    """Counts of confirmed (current), stale and missing reviews of the fixed responses."""
    cases = data.cases_by_id(cases_doc)
    current = reviews.current_reviews(reviews.load_doc(paths.REVIEWS_PATH, {"reviews": []}), "case_id")
    confirmed, stale = [], []
    for case_id, case in cases.items():
        review = current.get(case_id)
        if review is None:
            continue
        mismatched = reviews.stale_fields(review, data.case_binding(case, rubric_sha, rubric_version))
        (stale if mismatched else confirmed).append(case_id)
    return {"confirmed": confirmed, "stale": stale,
            "unreviewed": [c for c in cases if c not in confirmed and c not in stale]}


def validate_all() -> dict:
    problems, warnings, notes = [], [], []
    needed = [paths.CASES_PATH, paths.LABELS_PATH, paths.REVIEWS_PATH, paths.RUBRIC_PATH, paths.REPLAY_PATH,
              paths.JUDGE_PROMPT_PATH, paths.JUDGE_SCHEMA_PATH, paths.BUSINESS_RULES_PATH,
              *paths.RESPONSE_PROMPT_PATHS.values()]
    for path in needed:
        if not path.exists():
            problems.append(f"Missing file: {paths.display(path)}")
    if problems:
        return {"problems": problems, "warnings": warnings, "notes": notes, "case_count": 0}

    cases_doc, labels_doc, rubric = data.load_cases(), data.load_labels(), data.load_rubric()
    problems += check_rubric(rubric)
    problems += check_cases(cases_doc, defined_business_rules())
    problems += check_labels(labels_doc, data.ALL_CASE_IDS)
    problems += check_replay(data.load_replay(), data.ALL_CASE_IDS)
    problems += check_reviews(reviews.load_doc(paths.REVIEWS_PATH, {"reviews": []}), data.cases_by_id(cases_doc) if isinstance(cases_doc.get("cases"), list) else {})

    template = paths.JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    for placeholder in REQUIRED_PLACEHOLDERS:
        if placeholder not in template:
            problems.append(f"judge.txt: missing placeholder {placeholder}.")
    for forbidden in FORBIDDEN_IN_JUDGE_TEMPLATE:
        if forbidden in template:
            problems.append(f"judge.txt contains '{forbidden}'; the judge must not be told about answer keys, labels or prompt names.")
    for name, path in paths.RESPONSE_PROMPT_PATHS.items():
        if not path.read_text(encoding="utf-8").strip():
            problems.append(f"response_{name.lower()}.txt is empty.")

    cases = cases_doc.get("cases", [])
    labels = labels_doc.get("labels", [])
    status = review_status(cases_doc, data.sha256_file(paths.RUBRIC_PATH), str(rubric.get("version")))
    if labels:
        warnings.append(f"{len(labels)} proposed labels are unconfirmed trainer proposals (not human assessments).")
    if not status["confirmed"]:
        warnings.append(f"Confirmed human reviews: {len(status['confirmed'])}/{len(cases)}. Confirmed human agreement is unavailable until a trainer records reviews.")
    if status["stale"]:
        warnings.append(f"Stale human reviews (the case or rubric changed since they were made): {', '.join(status['stale'])}.")
    notes.append(data.dependency_note(cases_doc))
    return {
        "problems": problems, "warnings": warnings, "notes": notes, "case_count": len(cases),
        "development": sum(1 for c in cases if c.get("split") == "development"),
        "holdout": sum(1 for c in cases if c.get("split") == "holdout"),
        "proposed_labels": len(labels), "confirmed": status["confirmed"], "stale": status["stale"],
        "unreviewed": status["unreviewed"], "dataset_version": cases_doc.get("dataset_version"),
        "rubric_version": rubric.get("version"),
    }
