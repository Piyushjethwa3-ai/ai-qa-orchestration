"""
Command line for the evaluators.

    python -m evaluators trajectories                    # Week 5 agent, plain tools
    python -m evaluators trajectories --cases A-07 A-11
    python -m evaluators trajectories --out-dir reports/agent
    python -m evaluators audit-example                   # Day 6: deterministic redacted audit records
    python -m evaluators injection-demo                  # Day 6: prompt injection vs the real tool boundary

Exit code: 0 all cases passed, 1 completed but at least one case failed (the report is still saved),
2 invalid input. Each run is saved to a NEW folder <out-dir>/<run_id>/ (results.json, report.md); an
existing run is never overwritten. reports/ is git-ignored. No model is called.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluators import trajectory

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "reports" / "agent"


def _git_state() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"commit": run("rev-parse", "HEAD") or "unknown", "dirty": bool(run("status", "--porcelain"))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evaluators", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    traj = sub.add_parser("trajectories", help="Run the agent trajectory cases and save a report.")
    traj.add_argument("--cases", nargs="*", default=None, help="Case IDs to run (default: all).")
    traj.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    sub.add_parser("audit-example", help="Print the deterministic redacted audit example (JSON lines).")
    sub.add_parser("injection-demo", help="Run the prompt-injection enforcement demonstration (offline).")
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command == "injection-demo":
        from evaluators import injection_demo
        print(injection_demo.render(injection_demo.run_injection_demo()))
        return 0
    if args.command == "audit-example":
        from evaluators import audit_example
        for record in audit_example.build_example():
            print(json.dumps(record, sort_keys=True))
        return 0
    dataset = trajectory.load_dataset()
    problems = trajectory.validate_dataset(dataset)
    known = {c["case_id"] for c in dataset["cases"]}
    if problems or (args.cases and set(args.cases) - known):
        print("Invalid input:", problems or sorted(set(args.cases) - known), file=sys.stderr)
        return 2

    results = trajectory.run_dataset(dataset, args.cases)
    summary = trajectory.summarise(results)
    now = datetime.now(timezone.utc)
    run_id = f"traj-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
    run = {"run_id": run_id, "created_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "LOCAL_DETERMINISTIC_RULE_BASED_AGENT",
           "model_used": None, "note": "No language model was used. This evaluates the rule-based agent only.",
           "git": _git_state(), "dataset_version": dataset["dataset_version"],
           "dataset_sha256": trajectory.dataset_sha256(), "evaluator_version": trajectory.EVALUATOR_VERSION,
           "summary": summary, "results": results}
    folder = args.out_dir / run_id
    folder.mkdir(parents=True, exist_ok=False)
    with open(folder / "results.json", "x", encoding="utf-8") as handle:
        json.dump(run, handle, indent=1)
    lines = [f"# Agent trajectory run {run_id}", "", run["note"], "",
             f"Passed {summary['passed']} of {summary['total']}. Failed: {summary['failed_case_ids'] or 'none'}.", "",
             "| Case | Risk | Requirements | Result |", "| --- | --- | --- | --- |"]
    lines += [f"| {r['case_id']} | {r['risk']} | {', '.join(r['requirement_ids'])} | {r['result']} |" for r in results]
    for r in results:
        if r["findings"]:
            lines += ["", f"## {r['case_id']} FAIL", *[f"- {f}" for f in r["findings"]]]
    with open(folder / "report.md", "x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"{run_id}: passed {summary['passed']} of {summary['total']}; report in {folder}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
