"""
Command-line interface: `python -m training_day4 <command>`.

Contract commands:
  validate | show-case --case ID | access-check --mode live
  judge --mode replay|live --cases all|IDs      calibrate --run latest-fixed|RUN-ID
  compare --mode replay|live --cases all|IDs    repeat --mode replay|live --prompt A|B --cases IDs --runs N
  summary
Review commands (for the trainer's human assessments):
  review-fixed       confirm or correct the proposed label for one fixed response
  review-generated   review one answer generated in a compare or repeat run

Every command that calls the API needs an explicit --mode live. There is no default mode.
Exit codes: 0 fine; 1 a run was saved but is partial or failed; 2 refused or invalid input.
"""

import argparse
import sys

from training_day4 import checks, data, execute, judge, markdown, paths, reviews, rules, runstore, summary
from training_day4.execute import Context

CRITICAL_NONE = "NONE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m training_day4", description="Day 4: judge calibration, prompt comparison and repeat runs.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Check the data, labels, references, prompts and schemas.")

    show = sub.add_parser("show-case", help="Show one case, its fixed response, the rubric and labels.")
    show.add_argument("--case", required=True)

    access = sub.add_parser("access-check", help="Billable preflight: check model access (needs --mode live).")
    access.add_argument("--mode", required=True, choices=["live"])

    for name, help_text in (("judge", "Judge the eight fixed responses."), ("compare", "Compare response prompts A and B.")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--mode", required=True, choices=["replay", "live"])
        cmd.add_argument("--cases", nargs="+", default=["all"], help="'all' or case IDs, e.g. D4-01 D4-06")
        if name == "compare":
            cmd.add_argument("--seed", type=int, help="Seed for the local A/B execution order (default: random, recorded).")

    repeat = sub.add_parser("repeat", help="Generate and judge fresh responses several times.")
    repeat.add_argument("--mode", required=True, choices=["replay", "live"])
    repeat.add_argument("--prompt", required=True, choices=["A", "B"])
    repeat.add_argument("--cases", nargs="+", default=["D4-01", "D4-06", "D4-08"])
    repeat.add_argument("--runs", type=int, default=3)

    calibrate = sub.add_parser("calibrate", help="Compare a fixed-response judge run with human reviews.")
    calibrate.add_argument("--run", required=True, help="'latest-fixed' or a judge run ID")

    sub.add_parser("summary", help="Show which activities ran, and their status.")

    for name, help_text in (("review-fixed", "Record YOUR review of a fixed response."),
                            ("review-generated", "Record YOUR review of a generated answer.")):
        cmd = sub.add_parser(name, help=help_text)
        if name == "review-fixed":
            cmd.add_argument("--case", required=True)
            cmd.add_argument("--confirm-proposed", action="store_true",
                             help="Adopt the proposed scores as YOUR assessment (you still need --reason and --reviewer).")
        else:
            cmd.add_argument("--run", required=True)
            cmd.add_argument("--response", required=True, help="Response ID, e.g. R-1a2b3c4d")
        cmd.add_argument("--scores", nargs=4, type=int, metavar=("C", "R", "CO", "SP"),
                         help="correctness relevance completeness safety_and_policy, each 0, 1 or 2")
        cmd.add_argument("--critical", nargs="+", metavar="CATEGORY",
                         help="NONE, or critical categories: " + ", ".join(rules.CRITICAL_CATEGORIES))
        cmd.add_argument("--reason", required=True)
        cmd.add_argument("--reviewer", required=True, help="Your real name. Placeholders are refused.")
    return parser


def _show(path) -> str:
    return paths.display(path)


# ------------------------------------------------------------------ simple commands

def cmd_validate(_args, **_kw) -> int:
    result = checks.validate_all()
    for note in result["notes"]:
        print(f"note: {note}")
    for warning in result["warnings"]:
        print(f"WARNING (expected readiness gap, not malformed data): {warning}")
    if result["problems"]:
        for problem in result["problems"]:
            print(f"PROBLEM: {problem}")
        print(f"Day 4 data INVALID: {len(result['problems'])} problem(s).")
        return 2
    print(f"Day 4 data valid: {result['case_count']} cases ({result['development']} development, {result['holdout']} holdout), "
          f"dataset {result['dataset_version']}, rubric {result['rubric_version']}.")
    print(f"Proposed labels (unconfirmed trainer proposals): {result['proposed_labels']}")
    print(f"Confirmed human reviews: {len(result['confirmed'])}/{result['case_count']}   stale: {len(result['stale'])}")
    return 0


def cmd_show_case(args, **_kw) -> int:
    dataset = data.load_cases()
    case = data.cases_by_id(dataset).get(args.case)
    if case is None:
        print(f"Refused: unknown case {args.case!r}. Known cases: {', '.join(data.ALL_CASE_IDS)}", file=sys.stderr)
        return 2
    rubric = data.load_rubric()
    proposed = data.labels_by_id(data.load_labels()).get(args.case)
    current = reviews.current_reviews(reviews.load_doc(paths.REVIEWS_PATH, {"reviews": []}), "case_id").get(args.case)
    rsha = data.sha256_file(paths.RUBRIC_PATH)
    print(f"=== {case['case_id']} ({case['split']}) requirements: {', '.join(case['requirement_ids'])}")
    print(f"Request: {case['user_input']}")
    print(f"Approved context: {case['approved_context']}")
    print("Expected behaviour:\n  - " + "\n  - ".join(case["expected_behaviour"]))
    print("Prohibited behaviour:\n  - " + "\n  - ".join(case["prohibited_behaviour"]))
    print(f"Expected critical violations (answer key, never shown to the judge): {case['expected_critical_violations'] or 'none'}")
    print(f"FIXED RESPONSE: {case['fixed_response']}")
    print(f"{data.dependency_note(dataset)}")
    print("\n--- Rubric (day4 version %s) ---" % rubric["version"])
    for d in rubric["dimension_order"]:
        s = rubric["scales"][d]
        print(f"{d}: 0 = {s['0']} | 1 = {s['1']} | 2 = {s['2']}")
    print("Critical categories: " + ", ".join(rubric["critical_categories"]))
    print(f"Pass rule: {rubric['pass_rule']}")
    print("\n--- TRAINER-PROPOSED label (NOT a human assessment; unconfirmed) ---")
    if proposed:
        print(f"scores {proposed['scores']} | verdict {proposed['verdict']} | critical {proposed['critical_violations'] or 'none'}\nreason: {proposed['reason']}")
    else:
        print("none")
    print("\n--- CONFIRMED human review ---")
    if current is None:
        print("none recorded")
    else:
        stale = reviews.stale_fields(current, data.case_binding(case, rsha, str(rubric["version"])))
        print(f"{current['verdict']} by {current['reviewer']} at {current['reviewed_at']} scores {current['scores']} "
              f"critical {current['critical_violations'] or 'none'}\nreason: {current['reason']}\n"
              + (f"STALE: {', '.join(stale)} changed since this review." if stale else "Current: bound to the present case and rubric."))
    template = paths.JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    preview = judge.render_judge_prompt(template=template, response_id="R-preview", employee_request=case["user_input"],
                                        approved_context=case["approved_context"], candidate_response=case["fixed_response"],
                                        rubric_text=judge.render_rubric(rubric), critical_text=judge.render_critical_categories(rubric))
    print("\n--- Exactly what the judge would receive (no labels, answer keys, case ID or prompt name) ---")
    print(preview)
    return 0


def cmd_summary(_args, **_kw) -> int:
    print(summary.render_text(summary.collect()))
    return 0


# ------------------------------------------------------------------ running activities

def _print_run(run_dir, run, written) -> None:
    print(f"Run ID: {run['run_id']}")
    print(f"Mode: {run['mode'].upper()}   Status: {run['status']}")
    print(run["label"])
    if run.get("call_counts"):
        for name, c in run["call_counts"].items():
            if c["planned"]:
                if run["mode"] == "live":
                    print(f"  {name}: planned {c['planned']}, calls made {c['calls_made']}, API attempts {c['api_attempts']}, retries {c['retries']}, failed {c['failed']}, not attempted {c['not_attempted']}")
                else:
                    print(f"  {name}: planned {c['planned']}, replayed fixtures {c['replayed_items']}, API calls 0")
    if run.get("tally") and "pass" in run["tally"]:
        t = run["tally"]
        print(f"  judge verdicts: PASS {t['pass']}, FAIL {t['fail']}; evaluation errors/missing {t['evaluation_errors']}")
    for path in written:
        print(f"Report: {paths.display(path)}")


def _execute(kind: str, builder, ctx: Context) -> int:
    holder = {}

    def on_start(run):
        holder["dir"] = runstore.begin_run(run)
        holder["run"] = run

    try:
        run = builder(on_start)
    except Exception as exc:  # leave honest evidence rather than a silent half-run
        if "run" in holder:
            failed = holder["run"]
            failed["status"] = "failed"
            failed["limitations"] = [f"The run stopped early with {type(exc).__name__}: {exc}"] + failed.get("limitations", [])
            try:
                failed["call_counts"] = execute.count_calls(failed)
            except Exception:
                failed["call_counts"] = {}
            written = runstore.finish_run(holder["dir"], failed, f"# Run {failed['run_id']} failed\n\n{type(exc).__name__}: {runstore.client_module.redact(str(exc))}\n")
            print(f"The run stopped early ({type(exc).__name__}); evidence saved: {paths.display(written[0])}", file=sys.stderr)
            return 1
        raise
    human = summary.generated_reviews(holder["dir"]) if run["kind"] in ("compare", "repeat") else None
    written = runstore.finish_run(holder["dir"], run, markdown.render(run, human))
    _print_run(holder["dir"], run, written)
    return 0 if run["status"] == "completed" else 1


def _cases(args) -> list[dict] | None:
    try:
        return data.select_cases(args.cases, data.load_cases())
    except ValueError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return None


def _context(args, env, client, sleep, mode=None) -> Context:
    return Context(mode or args.mode, env=env, client=client, sleep=sleep)


def cmd_access_check(args, env=None, client=None, sleep=None) -> int:
    ctx = _context(args, env, client, sleep)
    for note in ctx.config.notes:
        print(f"note: {note}")
    code = _execute("access-check", lambda on_start: execute.run_access_check(ctx, on_start=on_start), ctx)
    return code


def cmd_judge(args, env=None, client=None, sleep=None) -> int:
    cases = _cases(args)
    if cases is None:
        return 2
    ctx = _context(args, env, client, sleep)
    return _execute("judge", lambda on_start: execute.run_judge(ctx, cases, on_start=on_start), ctx)


def cmd_compare(args, env=None, client=None, sleep=None) -> int:
    cases = _cases(args)
    if cases is None:
        return 2
    ctx = _context(args, env, client, sleep)
    return _execute("compare", lambda on_start: execute.run_compare(ctx, cases, seed=args.seed, on_start=on_start), ctx)


def cmd_repeat(args, env=None, client=None, sleep=None) -> int:
    cases = _cases(args)
    if cases is None:
        return 2
    if args.runs < 1:
        print("Refused: --runs must be at least 1.", file=sys.stderr)
        return 2
    ctx = _context(args, env, client, sleep)
    if args.mode == "replay" and not ctx.replay.has_repeat_prompt(args.prompt):
        print(f"Refused: no replay fixtures exist for prompt {args.prompt}.", file=sys.stderr)
        return 2
    return _execute("repeat", lambda on_start: execute.run_repeat(ctx, args.prompt, cases, args.runs, on_start=on_start), ctx)


def cmd_calibrate(args, **_kw) -> int:
    try:
        if args.run == "latest-fixed":
            judge_dir, judge_run = runstore.resolve_latest_fixed()
        else:
            judge_dir, judge_run = runstore.resolve_run(args.run)
            if judge_run["kind"] != "judge":
                raise runstore.RunStoreError(f"{judge_run['run_id']} is a {judge_run['kind']} run, not a fixed-response judge run.")
            if not judge_run["finalised"]:
                raise runstore.RunStoreError(f"{judge_run['run_id']} is unfinished and cannot be calibrated.")
    except runstore.RunStoreError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"Calibrating judge run {judge_run['run_id']} (mode {judge_run['mode'].upper()}, status {judge_run['status']})")
    run = execute.run_calibrate(judge_dir, judge_run)
    run_dir = runstore.begin_run(run)
    written = runstore.finish_run(run_dir, run, markdown.render(run))
    cov = run["coverage"]
    print(f"Run ID: {run['run_id']}   Status: {run['status']}")
    print(f"Source judge run: {judge_run['run_id']}   Source evidence mode: {judge_run['mode'].upper()}")
    print("Calibration execution: offline comparison of saved assessments (no model calls, no replay fixtures)")
    print(f"Confirmed human reviews: {cov['confirmed_human_reviews']}/{cov['cases']}   valid judge evaluations: {run['tally']['valid_judge_evaluations']}/{cov['cases']}")
    if not run["human_calibration"]["available"]:
        print("Confirmed human agreement: unavailable (no valid pairs with a confirmed human review).")
    else:
        m = run["human_calibration"]["all_cases"]
        print(f"Confirmed human agreement: {m['verdict_agreements']} of {m['valid_pairs']} valid pairs.")
    if judge_run["mode"] == "replay":
        print("REPLAY: a workflow demonstration, not validation of a live judge.")
    for path in written:
        print(f"Report: {paths.display(path)}")
    return 0


# ------------------------------------------------------------------ reviews

def _scores_and_critical(args, proposed: dict | None):
    if getattr(args, "confirm_proposed", False):
        if args.scores or args.critical:
            raise reviews.ReviewError("--confirm-proposed cannot be combined with --scores or --critical. Type your own scores instead to correct the proposal.")
        if proposed is None:
            raise reviews.ReviewError("There is no proposed label to confirm.")
        return dict(proposed["scores"]), list(proposed["critical_violations"]), "confirmed_proposed_label"
    if not args.scores or not args.critical:
        raise reviews.ReviewError("Give your own --scores C R CO SP and --critical NONE|CATEGORY..., or use --confirm-proposed.")
    critical = [] if [c.upper() for c in args.critical] == [CRITICAL_NONE] else [c.upper() for c in args.critical]
    if CRITICAL_NONE in [c.upper() for c in args.critical] and critical:
        raise reviews.ReviewError("NONE cannot be combined with critical categories.")
    return dict(zip(rules.DIMENSIONS, args.scores)), critical, "typed_scores"


def _print_review(review: dict, extra: str) -> None:
    print(f"Review recorded: {review['review_id']} by {review['reviewer']} at {review['reviewed_at']}")
    print(f"  scores {review['scores']} (total {review['total']}); critical {review['critical_violations'] or 'none'}")
    print(f"  verdict computed in code: {review['verdict']}   basis: {review['basis']}")
    print(f"  {extra}")


def cmd_review_fixed(args, **_kw) -> int:
    dataset = data.load_cases()
    case = data.cases_by_id(dataset).get(args.case)
    if case is None:
        print(f"Refused: unknown case {args.case!r}.", file=sys.stderr)
        return 2
    rubric = data.load_rubric()
    try:
        proposed = data.labels_by_id(data.load_labels()).get(args.case)
        scores, critical, basis = _scores_and_critical(args, proposed)
        existing = reviews.current_reviews(reviews.load_doc(paths.REVIEWS_PATH, {"reviews": []}), "case_id").get(args.case)
        review = reviews.build_review(
            target={"kind": "fixed_response", "case_id": args.case}, scores=scores, critical=critical, reason=args.reason,
            reviewer=args.reviewer, basis=basis, previous_id=existing["review_id"] if existing else None,
            bound_to=data.case_binding(case, data.sha256_file(paths.RUBRIC_PATH), str(rubric["version"])))
    except reviews.ReviewError as exc:
        print(f"Refused: {exc} Nothing was recorded.", file=sys.stderr)
        return 2
    reviews.append_review(paths.REVIEWS_PATH, {"reviews_version": "day4-v1", "reviews": []}, review, "case_id")
    _print_review(review, f"saved to {_show(paths.REVIEWS_PATH)}; the proposed label in human_labels.json is unchanged"
                  + (f"; supersedes {review['supersedes']}" if review["supersedes"] else ""))
    return 0


def cmd_review_generated(args, **_kw) -> int:
    try:
        run_dir, run = runstore.resolve_run(args.run)
    except runstore.RunStoreError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    if run["kind"] not in ("compare", "repeat") or not run["finalised"]:
        print("Refused: only finalised compare or repeat runs contain generated answers to review.", file=sys.stderr)
        return 2
    record = next((r for r in run["records"] if r["response_id"] == args.response), None)
    if record is None or record["candidate_response"] is None:
        print(f"Refused: no generated answer with response ID {args.response!r} in {run['run_id']}.", file=sys.stderr)
        return 2
    try:
        scores, critical, basis = _scores_and_critical(args, None)
        path = run_dir / runstore.REVIEWS_FILE
        existing = reviews.current_reviews(reviews.load_doc(path, {"reviews": []}), "response_id").get(args.response)
        review = reviews.build_review(
            target={"kind": "generated_response", "run_id": run["run_id"], "response_id": args.response, "case_id": record["case_id"]},
            scores=scores, critical=critical, reason=args.reason, reviewer=args.reviewer, basis=basis,
            previous_id=existing["review_id"] if existing else None,
            bound_to={"run_id": run["run_id"], "response_id": args.response, "response_sha256": record["response_sha256"],
                      "user_input_sha256": data.sha256_text(record["employee_request"]),
                      "approved_context_sha256": data.sha256_text(record["approved_context"]),
                      "rubric_version": run["rubric"]["version"], "rubric_sha256": run["rubric"]["sha256"]})
    except reviews.ReviewError as exc:
        print(f"Refused: {exc} Nothing was recorded.", file=sys.stderr)
        return 2
    reviews.append_review(path, {"run_id": run["run_id"], "reviews_version": "day4-v1", "reviews": []}, review, "response_id")
    _print_review(review, f"saved to {_show(path)}; run.json and the judge's assessment were not changed")
    return 0


COMMANDS = {
    "validate": cmd_validate, "show-case": cmd_show_case, "access-check": cmd_access_check, "judge": cmd_judge,
    "compare": cmd_compare, "repeat": cmd_repeat, "calibrate": cmd_calibrate, "summary": cmd_summary,
    "review-fixed": cmd_review_fixed, "review-generated": cmd_review_generated,
}


def main(argv: list[str] | None = None, *, env=None, client=None, sleep=None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args, env=env, client=client, sleep=sleep) if args.command in (
        "access-check", "judge", "compare", "repeat") else COMMANDS[args.command](args)
