"""
Evaluation output: one new folder per completed evaluation under reports/day5/, holding
results.json (all the evidence) and report.md (the readable view).

A run folder is created with exist_ok=False and its files with exclusive-create mode, so an
earlier run can never be overwritten. A completed evaluation is ALWAYS saved, including one
where cases fail. An evaluation that could not run (invalid input, an error) saves nothing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from day3_lab.runner import git_info, new_run_id as day3_new_run_id
from training_day5 import faults, metrics, paths
from training_day5.knowledge import Corpus, sha256_file

MODE = "LOCAL_DETERMINISTIC"
LIMITATIONS = (
    "Lexical scores are word-overlap counts. They are not confidence probabilities.",
    "A positive lexical score does not mean a document answers the question. Retrieval of a general document for an unsupported question is a recorded failure, not a hidden one.",
    "The scoring unit is the document ID. Passages inside a document are not scored, and there is no chunking.",
    "Ten cases are a classroom demonstration. They do not show that retrieval is reliable.",
    "This evaluates retrieval only. It says nothing about whether a model would use the documents correctly.",
)


class RunExistsError(FileExistsError):
    pass


def new_run_id() -> str:
    return "eval-" + day3_new_run_id()  # UTC timestamp plus a random suffix


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def build_run(evaluation: dict, corpus: Corpus, selected_ids: list[str], cases_path: Path, cases_doc: dict) -> dict:
    fault = evaluation["fault"]
    return {
        "run_id": new_run_id(),
        "created_at": utc_now(),
        "mode": MODE,
        "label": faults.SYNTHETIC_LABEL if fault["mode"] != "none" else None,
        "fault": fault,
        "git": git_info(),
        "hashes": {
            "knowledge_base_sha256": corpus.knowledge_base_sha256,
            "manifest_sha256": corpus.manifest_sha256,
            "dataset_sha256": sha256_file(cases_path),
            "policy_sha256": sha256_file(paths.POLICY_PATH) if Path(paths.POLICY_PATH).exists() else None,
        },
        "documents": [{"doc_id": d.doc_id, "os": d.os, "status": d.status, "version": d.version,
                       "content_sha256": d.content_sha256} for d in corpus.documents],
        "versions": {"retriever": evaluation["retriever_version"], "evaluator": evaluation["evaluator_version"],
                     "dataset": cases_doc.get("dataset_version")},
        "top_k": evaluation["top_k"],
        "selected_case_ids": selected_ids,
        "results": evaluation["results"],
        "aggregates": evaluation["aggregates"],
        "limitations": list(LIMITATIONS),
    }


def save_run(run: dict, markdown: str) -> tuple[Path, list[Path]]:
    run_dir = Path(paths.REPORTS_DIR) / run["run_id"]
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RunExistsError(f"Run folder {paths.display(run_dir)} already exists; earlier evidence is never overwritten.") from exc
    written = []
    for name, text in (("results.json", json.dumps(run, indent=2, ensure_ascii=False) + "\n"), ("report.md", markdown)):
        with open(run_dir / name, "x", encoding="utf-8") as handle:
            handle.write(text)
        written.append(run_dir / name)
    return run_dir, written


def _esc(value) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def _table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    return "\n".join(lines + ["| " + " | ".join(_esc(c) for c in row) + " |" for row in rows])


def _retrieved_text(result: dict) -> str:
    if not result["retrieved"]:
        return "(nothing retrieved)"
    parts = []
    for hit in result["retrieved"]:
        score = "synthetic" if hit["lexical_score"] is None else f"lexical score {hit['lexical_score']}"
        parts.append(f"{hit['rank']}. {hit['doc_id']} ({score})")
    return "; ".join(parts)


def render_markdown(run: dict) -> str:
    fault, agg = run["fault"], run["aggregates"]
    out = ["# Day 5 retrieval evaluation", ""]
    if run["label"]:
        out += [f"> **{run['label']}: {fault['mode']}. Fault status: {fault['status']}.**", ">", f"> {fault['note']}",
                "> Results below describe deliberately corrupted retrieval, not the normal retriever.", ""]
    out += [_table(["Field", "Value"], [
        ("Run ID", f"`{run['run_id']}`"), ("Created (UTC)", run["created_at"]), ("Mode", run["mode"]),
        ("Fault mode", fault["mode"]), ("Fault application", fault["status"]),
        ("Git commit", f"`{run['git']['commit']}` (dirty: {run['git']['dirty']})"), ("Top-k", run["top_k"]),
        ("Retriever / evaluator", f"{run['versions']['retriever']} / {run['versions']['evaluator']}"),
        ("Dataset version", run["versions"]["dataset"]),
        ("Knowledge-base hash", f"`{run['hashes']['knowledge_base_sha256'][:16]}…`"),
        ("Dataset hash", f"`{run['hashes']['dataset_sha256'][:16]}…`"),
        ("Cases", ", ".join(run["selected_case_ids"]))]), "",
        "## How cases are scored", "", agg["gate_explanation"], "",
        "Lexical scores are word-overlap counts, not confidence probabilities.", "",
        "## Summary", "",
        _table(["Measure", "Value"], [
            ("Cases passed / failed", f"{agg['passed']} / {agg['failed']} of {agg['cases']}"),
            ("Failed cases", ", ".join(agg["failed_case_ids"]) or "none"),
            ("Answerable cases passed", f"{agg['answerable_passed']} of {agg['answerable_cases']}"),
            ("Macro precision (answerable cases only)", metrics.display(agg["macro_precision"])),
            ("Macro recall (answerable cases only)", metrics.display(agg["macro_recall"])),
            ("Unanswerable cases passed (nothing retrieved)", f"{agg['unanswerable_passed']} of {agg['unanswerable_cases']}"),
            ("Prohibited-document failures", f"{agg['prohibited_failure_count']} ({', '.join(agg['prohibited_failure_cases']) or 'none'})")]), "",
        "## Per-case results", "",
        _table(["Case", "OS", "Answerable", "Expected", "Retrieved (rank, lexical score)", "Missing", "Prohibited returned",
                "Precision", "Recall", "Result"],
               [(r["case_id"], r["os"], "yes" if r["answerable"] else "no", ", ".join(r["expected_doc_ids"]) or "(none)",
                 _retrieved_text(r), ", ".join(r["missing_ids"]) or "none", ", ".join(r["prohibited_matches"]) or "none",
                 metrics.display(r["precision"]), metrics.display(r["recall"]), r["result"]) for r in run["results"]]), "",
        "## Explanations", ""]
    for r in run["results"]:
        out.append(f"- **{r['case_id']}** ({r['result']}): {r['explanation']} Query: \"{r['query']}\" (OS {r['os']}; {r['os_note']}).")
        if run["label"]:
            out.append(f"  - Fault ({r['fault']['status']}): {r['fault']['detail']}")
    out += ["", "## Limitations", ""] + [f"- {item}" for item in run["limitations"]] + [""]
    return "\n".join(out)
