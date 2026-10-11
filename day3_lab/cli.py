"""
Command-line interface: `python -m day3_lab <command>`.

This module only parses arguments, calls the other modules and prints
results. Commands:

  validate-data                     check cases, rubric and fixtures
  run --mode mock|live --out DIR    generate responses and save run.json/run.html
  open PATH                         open a saved report in the default browser
  review --report run.json --case ID --scores C R Co S --critical yes|no --note TEXT
  clinic [--variant corrected] --out DIR

Exit codes: 0 success; 1 run saved but contains provider ERROR records;
2 refused or invalid input (nothing was changed).
"""

import argparse
import getpass
import sys
import webbrowser
from pathlib import Path

from day3_lab.assessment import ReviewError, apply_review, make_assessment
from day3_lab.dataset import DIMENSIONS, validate_data
from day3_lab.report import (
    OutputExistsError,
    ensure_fresh_output_dir,
    load_run,
    save_reviewed_run,
    write_new_run,
)
from day3_lab.runner import UnknownCaseError, find_record, refresh, run_cases, run_clinic


def score_argument(text: str) -> int:
    # Accept exactly "0", "1" or "2". "2.0", "3", "-1" and "two" are rejected
    # rather than rounded or coerced.
    if text not in ("0", "1", "2"):
        raise argparse.ArgumentTypeError(f"score must be 0, 1 or 2, got {text!r}")
    return int(text)


def nonempty_text(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m day3_lab", description="Day 3 response-evaluation lab.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-data", help="Validate cases, rubric and fixtures.")

    run = sub.add_parser("run", help="Generate responses and save run.json and run.html.")
    run.add_argument("--mode", required=True, choices=["mock", "live"])
    run.add_argument("--case", help="Run one case ID, e.g. D3-01. Default: all cases.")
    run.add_argument("--out", required=True, type=Path, help="Fresh output directory.")

    open_cmd = sub.add_parser("open", help="Open a saved HTML report in the default browser.")
    open_cmd.add_argument("path", type=Path)

    review = sub.add_parser("review", help="Record YOUR human assessment of one response.")
    review.add_argument("--report", required=True, type=Path, help="Path to run.json.")
    review.add_argument("--case", required=True, help="Record ID, e.g. D3-01 or D3-04-unsafe.")
    review.add_argument(
        "--scores", required=True, nargs=4, type=score_argument,
        metavar=("CORRECTNESS", "RELEVANCE", "COMPLETENESS", "SAFETY"),
        help="Four scores, each 0, 1 or 2, in this order: " + ", ".join(DIMENSIONS),
    )
    review.add_argument("--critical", required=True, choices=["yes", "no"])
    review.add_argument("--note", required=True, type=nonempty_text, help="Reason for the scores.")
    review.add_argument("--reviewer", type=nonempty_text, help="Reviewer ID. Default: your OS user name.")

    clinic = sub.add_parser("clinic", help="Build the controlled failure clinic (fixed MOCK fixtures).")
    clinic.add_argument("--variant", choices=["original", "corrected"], default="original")
    clinic.add_argument("--out", required=True, type=Path, help="Fresh output directory.")
    return parser


def cmd_validate_data(_args) -> int:
    result = validate_data()
    for note in result["notes"]:
        print(f"note: {note}")
    for warning in result["warnings"]:
        print(f"WARNING (not a failure): {warning}")
    if result["problems"]:
        for problem in result["problems"]:
            print(f"PROBLEM: {problem}")
        print(f"Dataset INVALID: {len(result['problems'])} problem(s).")
        return 2
    print(
        f"Dataset valid: {result['case_count']} cases, unique IDs, "
        f"dataset {result['dataset_version']}, rubric {result['rubric_version']}."
    )
    print(f"count {result['case_count']}")
    return 0


def _print_run_summary(out_dir: Path, run: dict, written: list[Path]) -> None:
    summary = run["summary"]
    print(f"Saved: {', '.join(p.as_posix() for p in written)}")
    print(f"Mode: {run['provider_mode']}  model: {run.get('model')}")
    print(run["disclaimer"])
    print(f"Records: {summary['records']}")
    for group in ("provider", "structure", "human", "outcome"):
        counts = ", ".join(f"{k} {v}" for k, v in sorted(summary[group].items()))
        print(f"  {group:<9}: {counts}")
    for record in run["records"]:
        error = record["provider"].get("error")
        detail = f"  [{error['category']}: {error['message']}]" if error else ""
        print(f"  - {record['record_id']}: {record['outcome']['result']}{detail}")
    pending = [r["record_id"] for r in run["records"] if r["outcome"]["result"] == "REVIEW_PENDING"]
    if pending:
        print("Human review is still needed. Read each response, then for example:")
        print(
            f"  python -m day3_lab review --report {(out_dir / 'run.json').as_posix()} --case {pending[0]} "
            "--scores C R Co S --critical yes|no --note \"your reason\""
        )
    print(f"Open: python -m day3_lab open {(out_dir / 'run.html').as_posix()}")


def cmd_run(args) -> int:
    try:
        ensure_fresh_output_dir(args.out)  # check BEFORE any live call is made
        run = run_cases(args.mode, case_id=args.case)
        written = write_new_run(args.out, run)
    except (OutputExistsError, UnknownCaseError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    _print_run_summary(args.out, run, written)
    return 1 if run["summary"]["provider"].get("ERROR") else 0


def cmd_clinic(args) -> int:
    try:
        ensure_fresh_output_dir(args.out)
        run = run_clinic(args.variant)
        written = write_new_run(args.out, run)
    except OutputExistsError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    _print_run_summary(args.out, run, written)
    return 0


def cmd_open(args) -> int:
    path = args.path.resolve()
    if not path.is_file():
        print(f"Refused: {args.path} does not exist. Run a command that creates it first.", file=sys.stderr)
        return 2
    uri = path.as_uri()
    print(f"Opening {uri}")
    if not webbrowser.open(uri):
        print("No browser could be launched. Open the path above manually.")
    return 0


def cmd_review(args) -> int:
    if not args.report.is_file():
        print(f"Refused: report {args.report} does not exist.", file=sys.stderr)
        return 2
    run = load_run(args.report)
    try:
        record = find_record(run, args.case)
        if args.reviewer:
            reviewer, source = args.reviewer, "--reviewer argument"
        else:
            reviewer, source = getpass.getuser(), "operating-system user name"
        assessment = make_assessment(
            scores=args.scores,
            critical=args.critical == "yes",
            note=args.note,
            reviewer=reviewer,
            reviewer_source=source,
            response_hash=record["response_hash"] or "",
        )
        apply_review(record, assessment)
    except (UnknownCaseError, ReviewError) as exc:
        print(f"Refused: {exc} Nothing was changed.", file=sys.stderr)
        return 2
    refresh(run)
    html_path = save_reviewed_run(args.report, run)
    scores = ", ".join(f"{d} {assessment['scores'][d]}" for d in DIMENSIONS)
    print(f"Review recorded for {record['record_id']} by {reviewer} at {assessment['reviewed_at']}.")
    print(f"  {scores}; critical {args.critical}")
    print(f"  bound to response hash {record['response_hash'][:16]}…")
    print(f"  reviews in history: {len(record['human_assessment']['history'])}")
    print(f"Outcome: {record['outcome']['result']}: {record['outcome']['reason']}")
    print(f"Updated: {args.report.as_posix()} and {html_path.as_posix()}")
    return 0


COMMANDS = {
    "validate-data": cmd_validate_data,
    "run": cmd_run,
    "open": cmd_open,
    "review": cmd_review,
    "clinic": cmd_clinic,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
