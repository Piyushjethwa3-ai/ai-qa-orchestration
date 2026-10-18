"""
Run folders: one new, uniquely named folder per experiment under reports/day4/.

Lifecycle of a run.json:
  1. begin_run()  creates the folder (refuses if it exists) and writes run.json
                  with finalised=false, status "in_progress".
  2. finish_run() replaces that file ONCE with the final evidence (finalised=true)
                  and writes report.md. A finalised run is never rewritten, and
                  finish_run() refuses to touch one.
A run that crashed or was interrupted stays finalised=false, so it is visibly
unfinished and is never mistaken for a result.

Human reviews of generated answers are separate files (human_reviews.json) in the
run folder. Original run evidence is not edited to record a review.

Everything written is sanitised first: the API key (exact or key-like text,
including masked forms) is replaced with [REDACTED].
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from day3_lab.runner import new_run_id as day3_new_run_id
from training_day4 import client as client_module
from training_day4 import paths

RUN_FILE = "run.json"
REPORT_FILE = "report.md"
REVIEWS_FILE = "human_reviews.json"
REQUIRED_KEYS = ("run_id", "kind", "mode", "created_at", "finalised", "status")


class RunStoreError(RuntimeError):
    pass


def sanitise(obj):
    if isinstance(obj, str):
        return client_module.redact(obj)
    if isinstance(obj, list):
        return [sanitise(item) for item in obj]
    if isinstance(obj, dict):
        return {key: sanitise(value) for key, value in obj.items()}
    return obj


def new_run_id(kind: str, mode: str) -> str:
    return f"{kind}-{mode}-{day3_new_run_id()}"  # reuses the Day 3 timestamp+random suffix


def _atomic_write(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp, path)


def begin_run(run: dict) -> Path:
    run_dir = paths.REPORTS_DIR / run["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)  # raises FileExistsError: never reuse a folder
    placeholder = {**run, "finalised": False, "status": "in_progress"}  # the caller's dict is left as it is
    with open(run_dir / RUN_FILE, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitise(placeholder), indent=2, ensure_ascii=False) + "\n")
    return run_dir


def finish_run(run_dir: Path, run: dict, markdown: str) -> list[Path]:
    try:
        current = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunStoreError(f"Cannot finalise {run_dir.name}: run.json is unreadable ({exc}).") from exc
    if current.get("finalised") is not False or current.get("run_id") != run["run_id"]:
        raise RunStoreError(f"Refusing to overwrite {run_dir.name}: it is already finalised or does not match.")
    run["finalised"] = True
    _atomic_write(run_dir / RUN_FILE, json.dumps(sanitise(run), indent=2, ensure_ascii=False) + "\n")
    with open(run_dir / REPORT_FILE, "x", encoding="utf-8") as handle:
        handle.write(client_module.redact(markdown))
    return [run_dir / RUN_FILE, run_dir / REPORT_FILE]


@dataclass
class RunEntry:
    path: Path
    run: dict | None
    problem: str | None


def list_runs() -> list[RunEntry]:
    entries = []
    if not paths.REPORTS_DIR.exists():
        return entries
    for folder in sorted(p for p in paths.REPORTS_DIR.iterdir() if p.is_dir()):
        run_file = folder / RUN_FILE
        if not run_file.exists():
            entries.append(RunEntry(folder, None, "run.json is missing"))
            continue
        try:
            run = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            entries.append(RunEntry(folder, None, f"run.json is unreadable ({type(exc).__name__})"))
            continue
        missing = [key for key in REQUIRED_KEYS if key not in run]
        if not isinstance(run, dict) or missing:
            entries.append(RunEntry(folder, None, f"run.json is missing keys: {', '.join(missing) or 'not an object'}"))
        elif run["run_id"] != folder.name:
            entries.append(RunEntry(folder, None, "run_id does not match the folder name"))
        else:
            entries.append(RunEntry(folder, run, None))
    return entries


def resolve_run(ref: str) -> tuple[Path, dict]:
    """Find a run by folder name (run ID) or path."""
    candidate = Path(ref)
    folder = candidate if candidate.is_dir() else paths.REPORTS_DIR / ref
    if not folder.is_dir():
        raise RunStoreError(f"No run found for {ref!r}. Run IDs are folder names under reports/day4/.")
    for entry in list_runs():
        if entry.path.resolve() == folder.resolve():
            if entry.problem:
                raise RunStoreError(f"Run {folder.name} is corrupted: {entry.problem}.")
            return entry.path, entry.run
    raise RunStoreError(f"{ref!r} is not a run folder under reports/day4/.")


def resolve_latest_fixed() -> tuple[Path, dict]:
    """The most recent fixed-response judge run, or a clear refusal.

    Refuses (rather than quietly choosing something else) when any run metadata is
    corrupted, when the newest judge run is unfinished, or when two judge runs
    share the newest timestamp. It never falls back to an older run to hide a
    newer one that has errors; a finalised run with evaluation errors is returned
    and the errors stay visible downstream.
    """
    entries = list_runs()
    bad = [e for e in entries if e.problem]
    if bad:
        detail = "; ".join(f"{e.path.name}: {e.problem}" for e in bad)
        raise RunStoreError(f"Cannot choose 'latest-fixed' while run metadata is corrupted or unreadable ({detail}). Inspect or move those folders, or pass --run <run-id>.")
    judge_runs = sorted((e for e in entries if e.run["kind"] == "judge"), key=lambda e: e.run["created_at"])
    if not judge_runs:
        raise RunStoreError("No fixed-response judge run exists. Run: python -m training_day4 judge --mode replay --cases all")
    newest = judge_runs[-1]
    ties = [e for e in judge_runs if e.run["created_at"] == newest.run["created_at"]]
    if len(ties) > 1:
        raise RunStoreError("Ambiguous: " + ", ".join(e.path.name for e in ties) + " share the newest timestamp. Pass --run <run-id>.")
    if not newest.run["finalised"]:
        raise RunStoreError(f"The newest judge run {newest.path.name} is unfinished (status {newest.run['status']}). It was not replaced with an older run. Re-run the judge, or pass --run <run-id>.")
    return newest.path, newest.run
