"""
Builds run records for the `run` and `clinic` commands.

One "record" is one response being evaluated: the case and its approved
context, what the provider returned (raw and parsed), the structural
findings, the response hash, the human assessment (PENDING at first)
and the outcome. A "run" is a list of records plus metadata that lets
someone reproduce or audit it: run ID, time, git commit, dirty flag,
mode, model, and hashes of the prompt, dataset, rubric and schema.
"""

import subprocess
import uuid
from datetime import datetime, timezone

from day3_lab import paths
from day3_lab.assessment import decide_outcome, pending_assessment, utc_now
from day3_lab.dataset import (
    cases_by_id,
    load_cases,
    load_json,
    load_rubric,
    sha256_file,
    sha256_text,
)
from day3_lab.providers import MockProvider, OpenAILiveProvider, ProviderResult, mock_result
from day3_lab.validation import check_structure

MOCK_DISCLAIMER = (
    "MOCK: fixed, hand-written fixture responses. A passing mock run shows the fixtures and "
    "workflow work. It is NOT evidence of live model quality."
)
LIVE_DISCLAIMER = (
    "LIVE: real responses from the configured OpenAI model. One run is a single observation, "
    "not proof of reliable behaviour. Structure checks do not judge meaning."
)
CLINIC_DISCLAIMER = (
    "CONTROLLED FAILURE CLINIC: every response is a fixed MOCK fixture. No live calls were made. "
    "Teaching expectations are the lesson plan, not recorded human reviews."
)
CORRECTED_DISCLAIMER = (
    "CONTROLLED MOCK FIXTURE CORRECTION: these responses were corrected by hand to match the "
    "approved context. This is NOT proof that a live prompt improved."
)


class UnknownCaseError(ValueError):
    pass


def git_info() -> dict:
    """Commit hash and whether the working tree has uncommitted changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=paths.REPO_ROOT, capture_output=True, text=True, timeout=5
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=paths.REPO_ROOT, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unavailable", "dirty": None}
    if commit.returncode != 0 or status.returncode != 0:
        return {"commit": "unavailable", "dirty": None}
    return {"commit": commit.stdout.strip(), "dirty": bool(status.stdout.strip())}


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def build_record(record_id: str, case: dict, result: ProviderResult, extra: dict | None = None) -> dict:
    """Evaluate one provider result structurally and wrap it as a record."""
    parsed, structural = check_structure(result.raw_response)
    provider = result.to_dict()
    provider.pop("raw_response")  # stored once, at record level

    # A malformed LIVE response is a provider failure (ERROR), not a pass and
    # not a mock substitute. The raw text and findings are kept as evidence.
    if result.mode == "LIVE" and result.status == "OK" and structural["result"] != "PASS":
        provider["status"] = "ERROR"
        provider["error"] = {
            "category": "malformed_response",
            "message": "The live response did not pass the structural checks; see structural findings.",
        }

    record = {
        "record_id": record_id,
        "case_id": case["case_id"],
        "source": result.mode,
        "case": case,
        "provider": provider,
        "raw_response": result.raw_response,
        "parsed_response": parsed,
        "structural": structural,
        "response_hash": sha256_text(result.raw_response) if result.raw_response is not None else None,
        "human_assessment": pending_assessment(),
    }
    if extra:
        record.update(extra)
    record["outcome"] = decide_outcome(record)
    return record


def _run_metadata(kind: str, mode: str, model: str | None, disclaimer: str, variant: str | None = None) -> dict:
    dataset = load_cases()
    rubric = load_rubric()
    return {
        "run_id": new_run_id(),
        "created_at": utc_now(),
        "kind": kind,
        "variant": variant,
        "provider_mode": mode,
        "model": model,
        "disclaimer": disclaimer,
        "git": git_info(),
        "prompt": {"path": paths.display_path(paths.PROMPT_PATH), "sha256": sha256_file(paths.PROMPT_PATH)},
        "dataset": {
            "path": paths.display_path(paths.CASES_PATH),
            "version": dataset["dataset_version"],
            "sha256": sha256_file(paths.CASES_PATH),
        },
        "rubric": {
            "path": paths.display_path(paths.RUBRIC_PATH),
            "version": rubric["version"],
            "sha256": sha256_file(paths.RUBRIC_PATH),
            "dimension_order": rubric["dimension_order"],
            "scales": rubric["scales"],
            "decision_rule": rubric["decision_rule"],
        },
        "response_schema": {
            "path": paths.display_path(paths.RESPONSE_SCHEMA_PATH),
            "sha256": sha256_file(paths.RESPONSE_SCHEMA_PATH),
        },
    }


def summarise(run: dict) -> dict:
    counts: dict[str, dict[str, int]] = {"outcome": {}, "structure": {}, "provider": {}, "human": {}}
    for record in run["records"]:
        for key, value in (
            ("outcome", record["outcome"]["result"]),
            ("structure", record["structural"]["result"]),
            ("provider", record["provider"]["status"]),
            ("human", record["human_assessment"]["status"]),
        ):
            counts[key][value] = counts[key].get(value, 0) + 1
    return {"records": len(run["records"]), **counts}


def refresh(run: dict) -> dict:
    """Recompute every outcome and the summary (used after a review)."""
    for record in run["records"]:
        record["outcome"] = decide_outcome(record)
    run["summary"] = summarise(run)
    return run


def run_cases(mode: str, case_id: str | None = None, provider=None) -> dict:
    """Run the given provider (MOCK or LIVE) over one case or all cases."""
    dataset = load_cases()
    cases = dataset["cases"]
    if case_id is not None:
        cases = [case for case in cases if case["case_id"] == case_id]
        if not cases:
            known = ", ".join(case["case_id"] for case in dataset["cases"])
            raise UnknownCaseError(f"Unknown case {case_id!r}. Known cases: {known}")

    if provider is None:
        if mode == "mock":
            provider = MockProvider.from_file()
        else:
            provider = OpenAILiveProvider(paths.PROMPT_PATH.read_text(encoding="utf-8"))

    is_live = provider.mode == "LIVE"
    model = provider.requested_model if is_live else None
    run = _run_metadata("run", provider.mode, model, LIVE_DISCLAIMER if is_live else MOCK_DISCLAIMER)
    if is_live:
        run["live_adapter"] = {
            "api": "OpenAI Responses API with Structured Outputs (strict JSON schema)",
            "timeout_seconds": provider.timeout_seconds,
            "max_retries": provider.max_retries,
            "fallback_to_mock": False,
        }
    run["records"] = [build_record(case["case_id"], case, provider.respond(case)) for case in cases]
    if is_live:
        # Report the model the API says it used, if every record agrees on one.
        reported = {r["provider"]["model"] for r in run["records"] if r["provider"]["model"]}
        if len(reported) == 1:
            run["model"] = reported.pop()
        run["requested_model"] = model
    run["summary"] = summarise(run)
    return run


def exact_string_check(reference: str, actual: str) -> dict:
    """A deliberately naive evaluator, kept only to show why it is too strict."""
    return {
        "evaluator": "naive exact-string comparison of the 'answer' field",
        "reference": reference,
        "actual": actual,
        "result": "PASS" if actual == reference else "FAIL",
        "status": "DIAGNOSTIC ONLY - this is NOT the quality verdict and does not affect the outcome.",
        "why_it_misleads": (
            "Exact wording is not required. Case D3-02 explicitly prohibits requiring one exact "
            "reference sentence. Accurate alternative wording must be judged on meaning by a human."
        ),
    }


def run_clinic(variant: str = "original") -> dict:
    """Build the controlled failure clinic from fixed MOCK fixtures (no live calls)."""
    clinic = load_json(paths.CLINIC_FIXTURES_PATH)
    mock = load_json(paths.MOCK_RESPONSES_PATH)["responses"]
    cases = cases_by_id(load_cases())
    disclaimer = CLINIC_DISCLAIMER if variant == "original" else CLINIC_DISCLAIMER + " " + CORRECTED_DISCLAIMER

    run = _run_metadata("clinic", "MOCK", None, disclaimer, variant=variant)
    run["fixture_set"] = clinic["fixture_set"]
    run["records"] = []
    for fixture in clinic["variants"][variant]:
        extra = {
            "clinic": {
                "fixture_id": fixture["fixture_id"],
                "label": "CONTROLLED MOCK FIXTURE" + (" CORRECTION" if fixture.get("corrects") else ""),
                "purpose": fixture["purpose"],
                "corrects": fixture.get("corrects"),
                "teaching_expectation": fixture["teaching_expectation"],
                "teaching_expectation_status": "Lesson plan only. Not a recorded human review.",
            }
        }
        reference_case = fixture.get("exact_string_reference")
        if reference_case:
            extra["exact_string_check"] = exact_string_check(
                mock[reference_case]["answer"], fixture["response"]["answer"]
            )
        result = mock_result(fixture["response"], f"fixture {fixture['fixture_id']} has no response")
        run["records"].append(build_record(fixture["fixture_id"], cases[fixture["case_id"]], result, extra))
    run["summary"] = summarise(run)
    return run


def find_record(run: dict, record_id: str) -> dict:
    for record in run["records"]:
        if record["record_id"] == record_id:
            return record
    known = ", ".join(record["record_id"] for record in run["records"])
    raise UnknownCaseError(f"No record {record_id!r} in this report. Records: {known}")
