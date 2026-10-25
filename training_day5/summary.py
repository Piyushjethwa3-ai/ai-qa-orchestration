"""`summary --run latest`: show the newest saved evaluation, with its source run ID and fault mode."""

import json

from training_day5 import metrics, paths
from training_day5.knowledge import sha256_file

REQUIRED_KEYS = ("run_id", "created_at", "mode", "fault", "hashes", "results", "aggregates", "top_k")


class SummaryError(RuntimeError):
    pass


def list_runs() -> tuple[list[dict], list[tuple[str, str]]]:
    runs, bad = [], []
    root = paths.REPORTS_DIR
    if not root.exists():
        return runs, bad
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        result_file = folder / "results.json"
        if not result_file.exists():
            bad.append((folder.name, "results.json is missing"))
            continue
        try:
            run = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad.append((folder.name, "results.json is unreadable"))
            continue
        missing = [k for k in REQUIRED_KEYS if not isinstance(run, dict) or k not in run]
        if missing:
            bad.append((folder.name, f"results.json is missing {', '.join(missing)}"))
        elif run["run_id"] != folder.name:
            bad.append((folder.name, "run_id does not match the folder name"))
        else:
            runs.append(run)
    return runs, bad


def resolve(ref: str) -> dict:
    runs, bad = list_runs()
    if bad:
        raise SummaryError("Cannot choose a run while some run folders are corrupted or incomplete: "
                           + "; ".join(f"{name}: {why}" for name, why in bad))
    if not runs:
        raise SummaryError("No saved evaluation exists. Run: python -m training_day5 evaluate --cases all --top-k 3")
    if ref == "latest":
        runs.sort(key=lambda r: r["created_at"])
        ties = [r for r in runs if r["created_at"] == runs[-1]["created_at"]]
        if len(ties) > 1:
            raise SummaryError("Ambiguous: " + ", ".join(r["run_id"] for r in ties) + " share the newest timestamp. Pass --run <run-id>.")
        return runs[-1]
    for run in runs:
        if run["run_id"] == ref:
            return run
    raise SummaryError(f"No run {ref!r}. Run IDs are folder names under reports/day5/.")


def render(run: dict) -> str:
    agg, fault = run["aggregates"], run["fault"]
    drift = []
    if paths.CASES_PATH.exists() and sha256_file(paths.CASES_PATH) != run["hashes"]["dataset_sha256"]:
        drift.append("dataset")
    try:
        from training_day5.knowledge import load_corpus
        if load_corpus().knowledge_base_sha256 != run["hashes"]["knowledge_base_sha256"]:
            drift.append("knowledge base")
    except Exception:
        drift.append("knowledge base (cannot be loaded now)")
    lines = [f"Source run: {run['run_id']}", f"Created (UTC): {run['created_at']}   Mode: {run['mode']}",
             f"Fault mode: {fault['mode']}   Fault application: {fault['status']}"]
    if run.get("label"):
        lines.append(f"{run['label']}: results describe deliberately corrupted retrieval.")
    lines += [f"Top-k: {run['top_k']}   Git commit: {run['git']['commit'][:12]} (dirty: {run['git']['dirty']})",
              f"Knowledge base {run['hashes']['knowledge_base_sha256'][:12]}…   dataset {run['hashes']['dataset_sha256'][:12]}…"]
    if drift:
        lines.append(f"VERSION DRIFT: the {' and the '.join(drift)} changed since this run.")
    lines += ["", f"Cases passed {agg['passed']} of {agg['cases']}   failed: {', '.join(agg['failed_case_ids']) or 'none'}",
              f"Macro precision (answerable only): {metrics.display(agg['macro_precision'])}   macro recall: {metrics.display(agg['macro_recall'])}",
              f"Unanswerable passed: {agg['unanswerable_passed']} of {agg['unanswerable_cases']}   "
              f"prohibited-document failures: {agg['prohibited_failure_count']}", ""]
    for r in run["results"]:
        lines.append(f"  {r['case_id']}: {r['result']:<5} retrieved {', '.join(r['retrieved_ids']) or '(nothing)'}")
    lines += ["", f"Report: {paths.display(paths.REPORTS_DIR / run['run_id'] / 'report.md')}"]
    return "\n".join(lines)
