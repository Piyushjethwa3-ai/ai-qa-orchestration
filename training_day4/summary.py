"""
The `summary` command: which activities actually ran, from the evidence on disk.

Each activity is reported on its own, with live and replay kept apart. Runs are
never combined into one apparent experiment. Status words:
COMPLETED, PARTIAL (some evaluations missing), FAILED, UNFINISHED (interrupted
before finalising) and NOT RUN. Human review is never shown as complete unless
confirmed review records exist.
"""

import json

from training_day4 import checks, data, execute, paths, reviews, runstore

ACTIVITIES = [("access-check", "live"), ("judge", "replay"), ("judge", "live"), ("calibrate", "replay"),
              ("calibrate", "live"), ("compare", "replay"), ("compare", "live"), ("repeat", "replay"), ("repeat", "live")]
COMMANDS = {
    "access-check": "python -m training_day4 access-check --mode live",
    "judge": "python -m training_day4 judge --mode {mode} --cases all",
    "calibrate": "python -m training_day4 calibrate --run latest-fixed",
    "compare": "python -m training_day4 compare --mode {mode} --cases all",
    "repeat": "python -m training_day4 repeat --mode {mode} --prompt B --cases D4-01 D4-06 D4-08 --runs 3",
}
HASH_NAMES = {"dataset_cases_sha256": paths.CASES_PATH, "rubric_sha256": paths.RUBRIC_PATH,
              "judge_prompt_sha256": paths.JUDGE_PROMPT_PATH}


def evidence_mode(run: dict) -> str:
    """live or replay. A calibration is an offline comparison, so it is grouped by its SOURCE evidence mode.
    Calibrations saved before the mode was split out carry the source mode in `mode`."""
    return run.get("source_evidence_mode", run["mode"])


def status_word(run: dict) -> str:
    if not run["finalised"]:
        return "UNFINISHED"
    return {"completed": "COMPLETED", "partial": "PARTIAL", "failed": "FAILED"}.get(run["status"], run["status"].upper())


def version_drift(run: dict) -> list[str]:
    return [name.replace("_sha256", "") for name, path in HASH_NAMES.items()
            if run.get("hashes", {}).get(name) and run["hashes"][name] != data.sha256_file(path)]


def generated_reviews(run_dir) -> dict:
    doc = reviews.load_doc(run_dir / runstore.REVIEWS_FILE, {"reviews": []})
    return reviews.current_reviews(doc, "response_id")


def collect() -> dict:
    entries = runstore.list_runs()
    runs = [e for e in entries if e.run]
    corrupted = [(e.path.name, e.problem) for e in entries if e.problem]
    rows = []
    for kind, mode in ACTIVITIES:
        matching = [e for e in runs if e.run["kind"] == kind and evidence_mode(e.run) == mode]
        if not matching:
            rows.append({"activity": kind, "mode": mode, "status": "NOT RUN", "runs": 0, "command": COMMANDS[kind].format(mode=mode)})
            continue
        latest = sorted(matching, key=lambda e: e.run["created_at"])[-1]
        run = latest.run
        row = {"activity": kind, "mode": mode, "status": status_word(run), "runs": len(matching), "run_id": run["run_id"],
               "created_at": run["created_at"], "drift": version_drift(run), "tally": run.get("tally"), "dir": latest.path}
        if kind in ("compare", "repeat") and run["finalised"]:
            current = generated_reviews(latest.path)
            row["human_reviewed"] = f"{len(current)} of {len(run['records'])}"
            if kind == "compare":
                row["reading"] = execute.compare_assessment(run, current)["text"]
        if kind == "repeat":
            row["prompt"] = run.get("prompt")
        if kind == "calibrate":
            row["source_judge_run"] = run.get("source_judge_run", {}).get("run_id")
            row["confirmed_coverage"] = run.get("coverage", {}).get("confirmed_human_reviews")
        rows.append(row)
    return {"rows": rows, "corrupted": corrupted}


def render_text(summary: dict) -> str:
    cases_doc, rubric = data.load_cases(), data.load_rubric()
    status = checks.review_status(cases_doc, data.sha256_file(paths.RUBRIC_PATH), str(rubric.get("version")))
    total = len(cases_doc["cases"])
    lines = ["Day 4 summary (from the evidence on disk)", "",
             f"{'Activity':<14}{'Mode':<8}{'Status':<12}Latest run", "-" * 78]
    for row in summary["rows"]:
        lines.append(f"{row['activity']:<14}{row['mode']:<8}{row['status']:<12}{row.get('run_id', '-')}")
        if row["status"] == "NOT RUN":
            lines.append(f"{'':<34}to run: {row['command']}")
            continue
        if row.get("tally"):
            lines.append(f"{'':<34}{', '.join(f'{k} {v}' for k, v in row['tally'].items())}; runs of this kind: {row['runs']}")
        if row.get("prompt"):
            lines.append(f"{'':<34}latest run used response prompt {row['prompt']}; other prompts are separate runs")
        if row.get("drift"):
            lines.append(f"{'':<34}VERSION DRIFT: {', '.join(row['drift'])} changed since this run")
        if row.get("human_reviewed"):
            lines.append(f"{'':<34}human reviews of generated answers: {row['human_reviewed']}")
        if row.get("reading"):
            lines.append(f"{'':<34}provisional reading: {row['reading']}")
        if row.get("source_judge_run"):
            lines.append(f"{'':<34}calibrated judge run: {row['source_judge_run']}; confirmed human reviews used: {row['confirmed_coverage']}/{total}")
    lines += ["", "Human review of the fixed responses:",
              f"  confirmed: {len(status['confirmed'])}/{total}   stale: {len(status['stale'])}   unreviewed: {len(status['unreviewed'])}",
              f"  proposed (unconfirmed) labels: {total} - these are not human assessments",
              "  status: " + ("COMPLETE" if len(status["confirmed"]) == total and not status["stale"] else "NOT COMPLETE")]
    if summary["corrupted"]:
        lines += ["", "Unreadable or corrupted run folders (inspect them; they are not counted):"] + [f"  {n}: {p}" for n, p in summary["corrupted"]]
    lines += ["", "Live and replay runs are listed separately. Different runs are never combined into one experiment.",
              "Replay rows are teaching fixtures, not live observations."]
    return "\n".join(lines)
