"""
What the judge sees, and how its answer is validated.

ISOLATION. render_judge_prompt() takes only: an opaque response ID, the
employee request, the approved context, the candidate response, and the general
rubric and critical-category definitions as text. It has no parameter for human
labels (proposed or confirmed), expected verdicts, expected critical violations,
case-specific expected/prohibited-behaviour answer keys, case IDs or the prompt
label (A/B), so none of them can reach the judge. After judging, the code maps
the opaque response ID back to the case and prompt.

STRUCTURE. validate_judge_output() checks the raw text against
schemas/day4_judge_output.schema.json and then in code: integer scores 0-2 (not
booleans or floats), an allowed critical category, non-empty reasons, and a
response_id that matches the one that was sent. Anything else is an ERROR. The
total and the verdict are computed by rules.py. Malformed output, an API error
or a missing result is never a PASS and never a FAIL: it is an evaluation error.
"""

import json
from string import Template

from day3_lab.validation import check_structure
from training_day4 import paths, rules

_DELIMITERS = ("employee_request", "approved_context", "candidate_response")


def neutralise(text: str) -> str:
    """Stop data from closing its own delimiter block early."""
    text = str(text)
    for name in _DELIMITERS:
        text = text.replace(f"</{name}>", f"[/{name}]").replace(f"<{name}>", f"[{name}]")
    return text


def render_rubric(rubric: dict) -> str:
    lines = []
    for dimension in rubric["dimension_order"]:
        scale = rubric["scales"][dimension]
        lines.append(f"- {dimension}: 0 = {scale['0']} | 1 = {scale['1']} | 2 = {scale['2']}")
    for note in rubric.get("classification_notes", []):
        lines.append(f"- Note: {note}")
    return "\n".join(lines)


def render_critical_categories(rubric: dict) -> str:
    return "\n".join(f"- {name}: {meaning}" for name, meaning in rubric["critical_categories"].items())


def render_judge_prompt(*, template: str, response_id: str, employee_request: str, approved_context: str,
                        candidate_response: str, rubric_text: str, critical_text: str) -> str:
    return Template(template).substitute(
        response_id=response_id,
        rubric=rubric_text,
        critical_categories=critical_text,
        employee_request=neutralise(employee_request),
        approved_context=neutralise(approved_context),
        candidate_response=neutralise(candidate_response),
    )


def load_judge_schema() -> dict:
    with open(paths.JUDGE_SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def strict_output_schema() -> dict:
    """The schema in the form sent to OpenAI Structured Outputs (documentation keys removed)."""
    schema = load_judge_schema()
    for key in ("$schema", "title", "description"):
        schema.pop(key, None)
    return schema


def validate_judge_output(raw_text: str | None, expected_response_id: str) -> tuple[dict | None, list[dict]]:
    """Return (parsed_output, findings). parsed_output is None unless every check passed."""
    parsed, structural = check_structure(raw_text, schema=load_judge_schema())
    findings = list(structural["findings"])
    if structural["result"] != "PASS" or not isinstance(parsed, dict):
        return None, findings
    before = len(findings)

    def problem(path, message):
        findings.append({"stage": "code", "path": path, "message": message})

    if parsed["response_id"] != expected_response_id:
        problem("response_id", "The returned response_id does not match the one that was sent.")
    for dimension in rules.DIMENSIONS:
        value = parsed["scores"][dimension]
        if type(value) is not int or value not in (0, 1, 2):  # rejects True and 2.0
            problem(f"scores/{dimension}", f"Score must be the integer 0, 1 or 2, got {value!r}.")
        reason = parsed["reasons"][dimension]
        if not isinstance(reason, str) or not reason.strip():
            problem(f"reasons/{dimension}", "A non-empty reason is required.")
    for index, item in enumerate(parsed["critical_violations"]):
        if item not in rules.CRITICAL_CATEGORIES:
            problem(f"critical_violations/{index}", f"{item!r} is not an allowed critical category.")
    if len(set(parsed["critical_violations"])) != len(parsed["critical_violations"]):
        problem("critical_violations", "A critical category is listed more than once.")
    return (None, findings) if len(findings) > before else (parsed, findings)


def assess_output(raw_text: str | None, response_id: str, *, source: str, judge_model: str | None, sanitise) -> dict:
    """Turn raw judge text into a judge_assessment record. Total and verdict come from code."""
    parsed, findings = validate_judge_output(raw_text, response_id)
    base = {"source": source, "judge_model": judge_model,
            "raw_output": sanitise(raw_text) if raw_text is not None else None, "findings": findings}
    if parsed is None:
        return {**base, "status": "ERROR", "scores": None, "total": None, "critical_violations": None, "reasons": None,
                "verdict": None,
                "status_detail": "The judge output failed validation. This is an evaluation error, not a PASS or FAIL of the answer."}
    scores = {d: parsed["scores"][d] for d in rules.DIMENSIONS}
    critical = list(parsed["critical_violations"])
    return {**base, "status": "EVALUATED", "scores": scores, "total": rules.total_score(scores),
            "critical_violations": critical, "reasons": {d: parsed["reasons"][d] for d in rules.DIMENSIONS},
            "verdict": rules.verdict_from_scores(scores, critical),
            "status_detail": "Total and verdict computed in code from the validated scores and critical violations."}


def error_assessment(source: str, judge_model: str | None, detail: str, status: str = "ERROR", raw: str | None = None) -> dict:
    return {"status": status, "source": source, "judge_model": judge_model, "scores": None, "total": None,
            "critical_violations": None, "reasons": None, "verdict": None, "raw_output": raw,
            "findings": [], "status_detail": detail}
