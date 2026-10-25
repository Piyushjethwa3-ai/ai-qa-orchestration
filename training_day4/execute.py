"""
The Day 4 activities. Each builds a run dictionary; cli.py stores it.

Every per-response record keeps these four things SEPARATE:
  judge_assessment            what the LLM judge (or a replay fixture) said, validated in code
  trainer_proposed_label      a proposal from datasets/day4/human_labels.json (calibration only)
  confirmed_human_assessment  a named human's recorded review (never a judge score or a proposal)
  execution_error             why a result is missing: configuration, API, refusal, invalid output
A judge score is never stored in a human-assessment field.
"""

import random
import secrets
from datetime import datetime, timezone

from day3_lab.runner import git_info
from training_day4 import client as client_module
from training_day4 import data, heuristics, judge, paths, replay as replay_module, reviews, rules, runstore
from training_day4.config import Day4Config, load_config

UNAVAILABLE = client_module.UNAVAILABLE
REPLAY_CALL = {"source": "REPLAY", "api_calls": 0, "latency_ms": None, "usage": UNAVAILABLE,
               "note": "Authored fixture. No API call; latency and token usage are not available."}
HUMAN_PENDING = {"status": "PENDING", "note": "No human review recorded in this run folder. Generated answers need their own review."}
COMPARE_REPEAT_LIMITS = [
    "Observed variation can come from response generation, from judging, or from both. This workflow does not isolate those causes.",
    "A small number of observations does not guarantee future reliability.",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_response_id() -> str:
    return "R-" + secrets.token_hex(4)  # opaque: carries no case, prompt or label information


class Context:
    """Everything an activity needs: mode, config, client or replay fixtures, and frozen inputs."""

    def __init__(self, mode: str, env=None, client=None, replay=None, sleep=None):
        self.mode = mode
        self.config: Day4Config = load_config(env)
        self.dataset = data.load_cases()
        self.rubric = data.load_rubric()
        self.rubric_sha = data.sha256_file(paths.RUBRIC_PATH)
        self.judge_template = paths.JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
        self.rubric_text = judge.render_rubric(self.rubric)
        self.critical_text = judge.render_critical_categories(self.rubric)
        self.prompt_texts = {k: p.read_text(encoding="utf-8") for k, p in paths.RESPONSE_PROMPT_PATHS.items()}
        self.replay = replay if replay is not None else (replay_module.ReplayFixtures() if mode == "replay" else None)  # "offline": none needed
        if mode == "live":
            kwargs = {"env": env}
            if sleep is not None:
                kwargs["sleep"] = sleep
            self.client = client if client is not None else client_module.Day4Client(**kwargs)
        else:
            self.client = None

    @property
    def live_blocker(self) -> str | None:
        if self.mode == "live" and not self.config.ready:
            return " ".join(self.config.problems)
        return None


# ------------------------------------------------------------------ run skeleton

def base_run(ctx: Context, kind: str, extra: dict | None = None) -> dict:
    live = ctx.mode == "live"
    hashes = {
        "dataset_cases_sha256": data.sha256_file(paths.CASES_PATH),
        "rubric_sha256": ctx.rubric_sha,
        "judge_prompt_sha256": data.sha256_file(paths.JUDGE_PROMPT_PATH),
        "response_prompt_a_sha256": data.sha256_file(paths.RESPONSE_PROMPT_PATHS["A"]),
        "response_prompt_b_sha256": data.sha256_file(paths.RESPONSE_PROMPT_PATHS["B"]),
        "judge_output_schema_sha256": data.sha256_file(paths.JUDGE_SCHEMA_PATH),
    }
    if ctx.mode == "replay":  # only runs that actually use the fixtures record their hash
        hashes["replay_fixtures_sha256"] = data.sha256_file(paths.REPLAY_PATH)
    run = {
        "run_id": runstore.new_run_id(kind, ctx.mode),
        "kind": kind,
        "mode": ctx.mode,
        "label": ("LIVE - real model calls. One run is a single observation." if live else replay_module.REPLAY_LABEL),
        "mode_note": None if live else replay_module.REPLAY_NOTE,
        "created_at": utc_now(),
        "finalised": False,
        "status": "in_progress",
        "git": git_info(),
        "hashes": hashes,
        "rubric": {"version": ctx.rubric.get("version"), "sha256": ctx.rubric_sha},
        "dataset": {"version": ctx.dataset.get("dataset_version")},
        "prompts": {  # sanitised snapshots, enough to interpret the run later
            "judge_template": ctx.judge_template,
            "response_a": ctx.prompt_texts["A"],
            "response_b": ctx.prompt_texts["B"],
        },
        "models": (ctx.config.models_record() if live else {"generation": None, "judge": None,
                   "note": "Replay: no model was called." if ctx.mode == "replay" else "No model was called."}),
        "configuration_notes": ctx.config.notes if live else [],
        "settings": ({"generation": client_module.GENERATION_SETTINGS, "judge": client_module.JUDGE_SETTINGS,
                      "temperature": "not set (the model's default applies)", "sdk_retries": 0,
                      "max_attempts_per_call": client_module.MAX_ATTEMPTS,
                      "retry_policy": "transient errors only (timeout, connection, rate limit, 5xx); never to improve a score"}
                     if live else f"not applicable ({ctx.mode})"),
        "dependency_note": data.dependency_note(ctx.dataset),
        "records": [],
        "limitations": [],
    }
    if extra:
        run.update(extra)
    return run


# ------------------------------------------------------------------ one candidate

def make_record(ctx: Context, case: dict, *, kind: str, prompt: str | None = None, run_index: int | None = None) -> dict:
    item = case["case_id"] if kind == "fixed_response" else (
        f"{case['case_id']}/{prompt}" + (f"/run{run_index}" if run_index else ""))
    return {
        "item_id": item,
        "response_id": new_response_id(),
        "case_id": case["case_id"],
        "split": case["split"],
        "candidate_kind": kind,
        "prompt": prompt,
        "run_index": run_index,
        "employee_request": case["user_input"],
        "approved_context": case["approved_context"],
        "candidate_response": None,
        "response_sha256": None,
        "generation": None,
        "judge_input": None,
        "judge_call": None,
        "judge_assessment": None,
        "trainer_proposed_label": None,
        "confirmed_human_assessment": None,
        "human_review": dict(HUMAN_PENDING) if kind != "fixed_response" else
                        {"status": "SEE_DATASET", "note": "Fixed responses are reviewed in datasets/day4/human_reviews.json."},
        "execution_error": None,
        "heuristic_flags": [],
        "heuristic_note": heuristics.HEURISTIC_NOTE,
    }


def set_error(record: dict, stage: str, category: str, message: str) -> None:
    record["execution_error"] = {"stage": stage, "category": category, "message": client_module.redact(message)[:400]}


def set_candidate(record: dict, text: str | None) -> None:
    record["candidate_response"] = text
    if text is not None:
        record["response_sha256"] = data.sha256_text(text)
        record["heuristic_flags"] = heuristics.heuristic_flags(text, record["approved_context"])


def generate(ctx: Context, case: dict, record: dict, prompt: str, replay_text: str | None) -> bool:
    """Produce the candidate response for a generated record. Returns True on success."""
    if ctx.mode == "replay":
        record["generation"] = dict(REPLAY_CALL)
        if replay_text is None:
            set_error(record, "generation", "missing_fixture", "No replay fixture exists for this item.")
            return False
        set_candidate(record, replay_text)
        return True
    if ctx.live_blocker:
        set_error(record, "configuration", "missing_configuration", ctx.live_blocker)
        return False
    # Only the selected prompt, the employee request and the approved context are sent.
    input_text = f"Employee request:\n{case['user_input']}\n\nApproved context:\n{case['approved_context']}"
    result = ctx.client.call(model=ctx.config.generation_model, instructions=ctx.prompt_texts[prompt].strip(),
                             input_text=input_text, settings=client_module.GENERATION_SETTINGS)
    record["generation"] = {**result.to_record(), "source": "LIVE", "input_sha256": data.sha256_text(input_text)}
    if result.status != "OK":
        set_error(record, "generation", result.error["category"], result.error["message"])
        return False
    set_candidate(record, result.text)
    return True


def judge_candidate(ctx: Context, record: dict, replay_output: dict | None) -> None:
    """Judge record['candidate_response'] with only the allowed inputs. Sets judge_assessment."""
    source = "LIVE" if ctx.mode == "live" else "REPLAY"
    judge_model = ctx.config.judge_model if ctx.mode == "live" else None
    if record["candidate_response"] is None:
        record["judge_assessment"] = judge.error_assessment(
            source, judge_model, "No response was available to judge, so no evaluation exists.", status="MISSING")
        if record["execution_error"] is None:
            set_error(record, "judge", "no_response", "No response to judge.")
        return
    prompt_text = judge.render_judge_prompt(
        template=ctx.judge_template, response_id=record["response_id"], employee_request=record["employee_request"],
        approved_context=record["approved_context"], candidate_response=record["candidate_response"],
        rubric_text=ctx.rubric_text, critical_text=ctx.critical_text)
    record["judge_input"] = prompt_text  # the exact text the judge received, kept for inspection
    if ctx.mode == "replay":
        record["judge_call"] = dict(REPLAY_CALL)
        raw = ctx.replay.judge_text(replay_output, record["response_id"])
        if raw is None:
            record["judge_assessment"] = judge.error_assessment(source, None, "No replay judge fixture exists.", status="MISSING")
            set_error(record, "judge", "missing_fixture", "No replay judge fixture exists for this item.")
            return
    else:
        if ctx.live_blocker:
            record["judge_assessment"] = judge.error_assessment(source, judge_model, ctx.live_blocker, status="MISSING")
            set_error(record, "configuration", "missing_configuration", ctx.live_blocker)
            return
        result = ctx.client.call(model=ctx.config.judge_model, input_text=prompt_text, settings=client_module.JUDGE_SETTINGS,
                                 json_schema=judge.strict_output_schema(), schema_name="day4_judge")
        record["judge_call"] = {**result.to_record(), "source": "LIVE", "input_sha256": data.sha256_text(prompt_text)}
        if result.status != "OK":
            record["judge_assessment"] = judge.error_assessment(source, judge_model, "The judge call failed.", raw=result.text)
            set_error(record, "judge", result.error["category"], result.error["message"])
            return
        raw = result.text
    assessment = judge.assess_output(raw, record["response_id"], source=source, judge_model=judge_model, sanitise=runstore.sanitise)
    record["judge_assessment"] = assessment
    if assessment["status"] != "EVALUATED":
        set_error(record, "judge", "invalid_judge_output", "; ".join(f["message"] for f in assessment["findings"])[:300])


# ------------------------------------------------------------------ counts and status

def count_calls(run: dict) -> dict:
    live = run["mode"] == "live"
    out = {}
    for label, key, planned_where in (("generation", "generation", lambda r: r["candidate_kind"] == "generated_response"),
                                      ("judge", "judge_call", lambda r: True)):
        planned = [r for r in run["records"] if planned_where(r)]
        made = [r[key] for r in planned if r[key] and r[key].get("source") == "LIVE"]
        out[label] = {
            "planned": len(planned),
            "calls_made": len(made) if live else 0,
            "api_attempts": sum(c["attempt_count"] for c in made) if live else 0,
            "succeeded": sum(1 for c in made if c["status"] == "OK") if live else 0,
            "failed": sum(1 for c in made if c["status"] != "OK") if live else 0,
            "retries": sum(c["attempt_count"] - 1 for c in made) if live else 0,
            "not_attempted": sum(1 for r in planned if r[key] is None),
            "replayed_items": 0 if live else sum(1 for r in planned if r[key] and r[key].get("source") == "REPLAY"),
        }
    return out


def finalise(run: dict, limitations: list[str] | None = None) -> dict:
    records = run["records"]
    evaluated = [r for r in records if r["judge_assessment"] and r["judge_assessment"]["status"] == "EVALUATED"]
    run["call_counts"] = count_calls(run)
    run["tally"] = {
        "records": len(records),
        "evaluated": len(evaluated),
        "evaluation_errors": len(records) - len(evaluated),
        "pass": sum(1 for r in evaluated if r["judge_assessment"]["verdict"] == "PASS"),
        "fail": sum(1 for r in evaluated if r["judge_assessment"]["verdict"] == "FAIL"),
    }
    if records and len(evaluated) == len(records):
        run["status"] = "completed"
    elif evaluated:
        run["status"] = "partial"
    else:
        run["status"] = "failed"
    run["limitations"] = [*(limitations or []), *run.get("limitations", [])]
    return run


# ------------------------------------------------------------------ activities

def run_judge(ctx: Context, cases: list[dict], on_start=None) -> dict:
    run = base_run(ctx, "judge", {"subject": "fixed_responses", "case_ids": [c["case_id"] for c in cases]})
    if on_start:
        on_start(run)
    for case in cases:
        record = make_record(ctx, case, kind="fixed_response")
        set_candidate(record, case["fixed_response"])
        judge_candidate(ctx, record, ctx.replay.doc["judge_fixed"].get(case["case_id"]) if ctx.replay else None)
        run["records"].append(record)
    return finalise(run, ["The judge sees only the request, approved context, response, rubric and critical-category definitions. "
                          "Proposed and confirmed human labels are not part of this run."])


def run_compare(ctx: Context, cases: list[dict], seed: int | None = None, on_start=None) -> dict:
    seed = seed if seed is not None else random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)
    orders = {}
    for case in cases:
        order = ["A", "B"]
        rng.shuffle(order)
        orders[case["case_id"]] = order
    run = base_run(ctx, "compare", {
        "case_ids": [c["case_id"] for c in cases],
        "ordering": {"seed": seed, "method": "random.Random(seed).shuffle(['A','B']) for each case, in case order",
                     "per_case_order": orders,
                     "note": "The seed only fixes the local A/B execution order. It does not make model responses reproducible."},
    })
    if on_start:
        on_start(run)
    for case in cases:
        for prompt in orders[case["case_id"]]:
            record = make_record(ctx, case, kind="generated_response", prompt=prompt)
            replay_text, replay_output = ctx.replay.compare_entry(case["case_id"], prompt) if ctx.replay else (None, None)
            if generate(ctx, case, record, prompt, replay_text):
                judge_candidate(ctx, record, replay_output)
            else:
                judge_candidate(ctx, record, None)
            run["records"].append(record)
    return finalise(run, [
        "Generated answers are not covered by the fixed-response labels. They need their own human review before any prompt is selected.",
        "Each case is a separate observation, but cases that share a request and context are not independent.",
        *COMPARE_REPEAT_LIMITS,
    ])


def run_repeat(ctx: Context, prompt: str, cases: list[dict], runs: int, on_start=None) -> dict:
    run = base_run(ctx, "repeat", {"prompt": prompt, "case_ids": [c["case_id"] for c in cases], "runs_per_case": runs})
    if on_start:
        on_start(run)
    for case in cases:
        for index in range(1, runs + 1):
            record = make_record(ctx, case, kind="generated_response", prompt=prompt, run_index=index)
            replay_text, replay_output = ctx.replay.repeat_entry(prompt, case["case_id"], index) if ctx.replay else (None, None)
            if generate(ctx, case, record, prompt, replay_text):
                judge_candidate(ctx, record, replay_output)
            else:
                judge_candidate(ctx, record, None)
            run["records"].append(record)
    limitations = list(COMPARE_REPEAT_LIMITS)
    if ctx.mode == "replay":
        limitations.insert(0, "Replay 'runs' are fixed, scripted examples. They cannot measure consistency or model variation.")
    return finalise(run, limitations)


def run_access_check(ctx: Context, on_start=None) -> dict:
    run = base_run(ctx, "access-check")
    run["mode"] = "live"
    if on_start:
        on_start(run)
    if ctx.live_blocker:
        run["records"].append({"item_id": "configuration", "role": "configuration", "status": "ERROR",
                               "error": {"category": "missing_configuration", "message": ctx.live_blocker}})
        run["status"] = "failed"
        run["tally"] = {"checks": 1, "ok": 0, "errors": 1}
        return run
    targets = [("generation", ctx.config.generation_model)]
    if ctx.config.judge_model != ctx.config.generation_model:
        targets.append(("judge", ctx.config.judge_model))
    else:
        targets[0] = ("generation and judge (same model, checked once)", ctx.config.generation_model)
    for role, model in targets:
        result = ctx.client.call(model=model, input_text="Reply with the single word OK.", settings={"max_output_tokens": 16})
        run["records"].append({"item_id": role, "role": role, "model_requested": model,
                               "status": result.status, "call": result.to_record(), "error": result.error})
    ok = sum(1 for r in run["records"] if r["status"] == "OK")
    run["tally"] = {"checks": len(run["records"]), "ok": ok, "errors": len(run["records"]) - ok}
    run["status"] = "completed" if ok == len(run["records"]) else ("partial" if ok else "failed")
    run["limitations"] = ["A successful access check shows only that these model IDs answered a tiny request just now."]
    return run


# ------------------------------------------------------------------ calibration

def _pair_metrics(pairs: list[dict]) -> dict:
    n = len(pairs)
    dimension_counts = {d: 0 for d in rules.DIMENSIONS}
    details, critical, false_pass, false_fail, agree = [], [], [], [], 0
    for pair in pairs:
        judge_side, ref = pair["judge"], pair["reference"]
        if judge_side["verdict"] == ref["verdict"]:
            agree += 1
        elif judge_side["verdict"] == "PASS":
            false_pass.append(pair["case_id"])
        else:
            false_fail.append(pair["case_id"])
        differing = [{"dimension": d, "judge": judge_side["scores"][d], "reference": ref["scores"][d]}
                     for d in rules.DIMENSIONS if judge_side["scores"][d] != ref["scores"][d]]
        for item in differing:
            dimension_counts[item["dimension"]] += 1
        if differing:
            details.append({"case_id": pair["case_id"], "differences": differing})
        if set(judge_side["critical_violations"]) != set(ref["critical_violations"]):
            critical.append({"case_id": pair["case_id"], "judge": judge_side["critical_violations"],
                             "reference": ref["critical_violations"]})
    return {"valid_pairs": n, "verdict_agreements": agree, "verdict_disagreements": n - agree,
            "false_passes": false_pass, "false_fails": false_fail, "critical_disagreements": critical,
            "per_dimension_disagreement_counts": dimension_counts, "per_dimension_details": details}


def run_calibrate(judge_dir, judge_run: dict) -> dict:
    ctx = Context("offline")  # reuses the frozen inputs and hashes only; calibrate calls no model and uses no replay fixtures
    cases = data.cases_by_id(ctx.dataset)
    proposed = data.labels_by_id(data.load_labels())
    review_doc = reviews.load_doc(paths.REVIEWS_PATH, {"reviews": []})
    current = reviews.current_reviews(review_doc, "case_id")
    by_case = {r["case_id"]: r for r in judge_run["records"]}

    source_mode = judge_run["mode"]
    run = base_run(ctx, "calibrate", {
        # An offline comparison of SAVED assessments. It is neither live nor replay evidence itself.
        "run_id": runstore.new_run_id("calibrate", f"offline-from-{source_mode}"),
        "mode": "offline",
        "execution": "offline comparison of saved assessments (no model calls, no replay fixtures)",
        "source_evidence_mode": source_mode,
        "source_judge_run": {"run_id": judge_run["run_id"], "mode": judge_run["mode"], "status": judge_run["status"],
                             "created_at": judge_run["created_at"], "directory": paths.display(judge_dir),
                             "hashes": judge_run["hashes"], "models": judge_run["models"]},
    })
    run["label"] = (f"OFFLINE CALIBRATION of a {source_mode.upper()} fixed-response judge run. "
                    "This step made no model calls and used no replay fixtures.")
    run["mode_note"] = ("Calibration is an offline comparison of saved assessments. The evidence mode "
                        f"({source_mode.upper()}) belongs to the source judge run, not to this calibration. "
                        + (replay_module.REPLAY_NOTE if source_mode == "replay" else ""))
    run["models"] = {"note": "calibrate calls no model. The judge models are recorded in source_judge_run.models."}
    run["settings"] = "not applicable (calibrate makes no calls)"
    run["configuration_notes"] = []
    run["hashes"]["labels_sha256"] = data.sha256_file(paths.LABELS_PATH)
    run["hashes"]["human_reviews_sha256"] = data.sha256_file(paths.REVIEWS_PATH)
    drift = [name for name in ("dataset_cases_sha256", "rubric_sha256", "judge_prompt_sha256")
             if judge_run["hashes"].get(name) != run["hashes"].get(name)]
    run["version_drift"] = {"differs_from_current_files": drift,
                            "note": "These inputs changed after the judge run. Results below may not describe the current files." if drift else "Judge run inputs match the current files."}

    rows, confirmed_pairs, proposed_pairs = [], [], []
    for case_id, case in cases.items():
        record = by_case.get(case_id)
        assessment = (record or {}).get("judge_assessment")
        judge_view = ({"status": assessment["status"], "verdict": assessment["verdict"], "scores": assessment["scores"],
                       "critical_violations": assessment["critical_violations"], "reasons": assessment["reasons"],
                       "response_id": record["response_id"]}
                      if assessment else {"status": "MISSING", "verdict": None, "scores": None, "critical_violations": None,
                                          "reasons": None, "response_id": None})
        label = proposed.get(case_id)
        review = current.get(case_id)
        human = {"status": "NONE", "detail": "No confirmed human review recorded."}
        if review:
            mismatched = reviews.stale_fields(review, data.case_binding(case, ctx.rubric_sha, str(ctx.rubric.get("version"))))
            human = ({"status": "STALE", "detail": f"Bound fingerprints changed: {', '.join(mismatched)}.", "review_id": review["review_id"]}
                     if mismatched else
                     {"status": "CONFIRMED", "review_id": review["review_id"], "reviewer": review["reviewer"],
                      "reviewed_at": review["reviewed_at"], "verdict": review["verdict"], "scores": review["scores"],
                      "critical_violations": review["critical_violations"], "reason": review["reason"], "basis": review["basis"]})
        rows.append({"case_id": case_id, "split": case["split"], "judge_assessment": judge_view,
                     "trainer_proposed_label": ({"label_source": "trainer_proposed", "human_confirmed": False, "verdict": label["verdict"],
                                                 "scores": label["scores"], "critical_violations": label["critical_violations"]}
                                                if label else None),
                     "confirmed_human_assessment": human,
                     "execution_error": (record or {}).get("execution_error") if record else
                                        {"stage": "calibration", "category": "no_judge_record", "message": "The judge run has no record for this case."}})
        if judge_view["status"] == "EVALUATED":
            if human["status"] == "CONFIRMED":
                confirmed_pairs.append({"case_id": case_id, "split": case["split"], "judge": judge_view, "reference": human})
            if label:
                proposed_pairs.append({"case_id": case_id, "split": case["split"], "judge": judge_view,
                                       "reference": {"verdict": label["verdict"], "scores": label["scores"],
                                                     "critical_violations": label["critical_violations"]}})

    def by_split(pairs):
        return {"development": _pair_metrics([p for p in pairs if p["split"] == "development"]),
                "holdout": _pair_metrics([p for p in pairs if p["split"] == "holdout"]),
                "all_cases": _pair_metrics(pairs)}

    total = len(rows)
    confirmed_n = sum(1 for r in rows if r["confirmed_human_assessment"]["status"] == "CONFIRMED")
    run["rows"] = rows
    run["coverage"] = {
        "cases": total,
        "confirmed_human_reviews": confirmed_n,
        "stale_human_reviews": sum(1 for r in rows if r["confirmed_human_assessment"]["status"] == "STALE"),
        "cases_without_confirmed_review": total - confirmed_n,
        "cases_without_valid_judge_evaluation": sum(1 for r in rows if r["judge_assessment"]["status"] != "EVALUATED"),
        "week2_target_confirmed_human_labels": 15,
        "gap_to_week2_target": max(15 - confirmed_n, 0),
    }
    run["human_calibration"] = {"basis": "confirmed, current, non-stale human reviews only",
                                "available": bool(confirmed_pairs), **by_split(confirmed_pairs)}
    run["provisional_proposed_label_comparison"] = {
        "basis": "PROVISIONAL - trainer-PROPOSED labels that no human has confirmed. This is not human calibration.",
        **by_split(proposed_pairs)}
    run["records"] = []  # per-case detail is in 'rows'
    run["tally"] = {"cases": total, "confirmed_human_reviews": confirmed_n,
                    "valid_judge_evaluations": total - run["coverage"]["cases_without_valid_judge_evaluation"]}
    run["status"] = "completed"
    run["limitations"] = [
        "Calibration is an offline comparison of saved assessments. It is not itself live or replay evidence.",
        "Eight examples demonstrate the classroom workflow. They do not show that a judge is reliable.",
        "The broader Week 2 target is at least 15 genuinely human-labelled responses plus wider coverage. Cases are not duplicated to reach it.",
        data.dependency_note(ctx.dataset),
        "The holdout label supports classroom discipline, not a strong independent benchmark. Do not tune against holdout outcomes.",
    ]
    if judge_run["mode"] == "replay":
        run["limitations"].insert(0, "REPLAY: the judge outputs are authored fixtures. This is a workflow demonstration, not validation of a live judge.")
    return run


# ------------------------------------------------------------------ comparison reading

def compare_assessment(run: dict, human_current: dict[str, dict] | None = None) -> dict:
    """A provisional reading of a compare run. It never forces a winner.

    human_current maps response_id -> the current human review of that generated answer.
    """
    human_current = human_current or {}
    records = run["records"]
    prompts = ("A", "B")
    tallies = {p: {"pass": 0, "fail": 0, "error": 0, "critical_judge": 0, "critical_human": 0,
                   "human_reviewed": 0, "human_pass": 0, "human_fail": 0} for p in prompts}
    for record in records:
        t = tallies[record["prompt"]]
        assessment = record["judge_assessment"]
        if assessment["status"] == "EVALUATED":
            t["pass" if assessment["verdict"] == "PASS" else "fail"] += 1
            t["critical_judge"] += 1 if assessment["critical_violations"] else 0
        else:
            t["error"] += 1
        review = human_current.get(record["response_id"])
        if review:
            t["human_reviewed"] += 1
            t["human_pass" if review["verdict"] == "PASS" else "human_fail"] += 1
            t["critical_human"] += 1 if review["critical_violations"] else 0
    per_prompt = len(records) // 2 if records else 0
    reviewed_all = bool(records) and all(t["human_reviewed"] == per_prompt for t in tallies.values()) and per_prompt > 0
    both_critical = all(t["critical_judge"] + t["critical_human"] > 0 for t in tallies.values())
    errors = sum(t["error"] for t in tallies.values())
    if run["mode"] == "replay":
        text = "Inconclusive. Replay fixtures are authored teaching examples and say nothing about either prompt."
        preference = "inconclusive"
    elif both_critical:
        text = "Neither prompt can be recommended for approval on this evidence: both produced critical violations."
        preference = "none"
    elif errors:
        text = f"Inconclusive. {errors} evaluation(s) are missing or errored."
        preference = "inconclusive"
    elif not reviewed_all:
        reviewed = sum(t["human_reviewed"] for t in tallies.values())
        text = (f"Inconclusive until a human has reviewed every generated answer ({reviewed} of {len(records)} reviewed). "
                "Judge-only counts are provisional.")
        preference = "inconclusive"
    else:
        a, b = tallies["A"]["human_pass"], tallies["B"]["human_pass"]
        if a == b:
            text, preference = f"Inconclusive. Human-reviewed PASS counts are equal ({a} each).", "inconclusive"
        else:
            winner = "A" if a > b else "B"
            text = (f"Provisional preference: Prompt {winner} (human-reviewed PASS: A {a}, B {b}). This is one run of dependent "
                    "examples and is not an approval or a statement of reliability.")
            preference = f"provisional_{winner}"
    return {"preference": preference, "text": text, "tallies": tallies}
