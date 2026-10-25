"""Readable Markdown for each report. Pure formatting: no decisions are made here."""

from training_day4 import rules
from training_day4.execute import compare_assessment

SHORT = {"correctness": "C", "relevance": "R", "completeness": "Co", "safety_and_policy": "S&P"}


def esc(value) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(esc(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def scores_text(assessment) -> str:
    if not assessment or not assessment.get("scores"):
        return "n/a"
    return " ".join(f"{SHORT[d]} {assessment['scores'][d]}" for d in rules.DIMENSIONS) + f" (total {assessment['total']})"


def outcome_text(assessment) -> str:
    if not assessment:
        return "MISSING"
    return assessment["verdict"] if assessment["status"] == "EVALUATED" else f"EVALUATION {assessment['status']}"


def latency_text(call) -> str:
    if not call or call.get("source") == "REPLAY":
        return "unavailable (replay)" if call else "n/a"
    return "unavailable" if call.get("latency_ms") is None else f"{call['latency_ms']} ms"


def usage_text(call) -> str:
    if not call or call.get("source") == "REPLAY":
        return "unavailable (replay)" if call else "n/a"
    usage = call.get("usage")
    if not isinstance(usage, dict):
        return "unavailable"
    return f"in {usage.get('input_tokens')} / out {usage.get('output_tokens')} / total {usage.get('total_tokens')}"


def header(run: dict) -> str:
    models = run["models"]
    model_line = (models["note"] if "note" in models else
                  f"generation `{models['generation']}`; judge `{models['judge']}` (from {models['judge_model_source']}); "
                  f"same model for generation and judging: {models['same_model_for_generation_and_judging']}")
    if run["kind"] == "calibrate":
        mode_rows = [("Calibration execution", run["execution"]),
                     ("Source judge run", f"`{run['source_judge_run']['run_id']}`"),
                     ("Source evidence mode", run["source_evidence_mode"].upper())]
    else:
        mode_rows = [("Mode", run["mode"].upper())]
    out = [
        f"# Day 4 {run['kind']} report",
        "",
        f"> **{run['label']}**",
    ]
    if run.get("mode_note"):
        out += [">", f"> {run['mode_note']}"]
    out += [
        "",
        table(["Field", "Value"], [
            ("Run ID", f"`{run['run_id']}`"), *mode_rows, ("Status", run["status"]),
            ("Created", run["created_at"]), ("Git commit", f"`{run['git']['commit']}` (dirty: {run['git']['dirty']})"),
            ("Models", model_line), ("Generation settings", run["settings"] if isinstance(run["settings"], str) else
                                     f"{run['settings']['generation']}; temperature {run['settings']['temperature']}; max attempts per call {run['settings']['max_attempts_per_call']}"),
            ("Dataset / rubric", f"{run['dataset']['version']} / {run['rubric']['version']}"),
            ("Hashes (short)", ", ".join(f"{k.replace('_sha256', '')} `{v[:10]}`" for k, v in run["hashes"].items())),
        ]),
        "",
    ]
    if run.get("configuration_notes"):
        out += ["Configuration notes: " + " ".join(run["configuration_notes"]), ""]
    out += [f"**Dataset note.** {run['dependency_note']}", ""]
    return "\n".join(out)


def counts_block(run: dict) -> str:
    c = run["call_counts"]
    rows = [(name, v["planned"], v["calls_made"], v["api_attempts"], v["retries"], v["succeeded"], v["failed"], v["not_attempted"], v["replayed_items"])
            for name, v in c.items()]
    t = run["tally"]
    return "\n".join([
        "## Calls and outcomes", "",
        table(["Call type", "Planned", "Calls made", "API attempts", "Retries", "Succeeded", "Failed", "Not attempted", "Replayed items"], rows),
        "", f"Judge verdicts: PASS {t['pass']}, FAIL {t['fail']}; evaluation errors/missing: {t['evaluation_errors']} (these are not PASS or FAIL of the answer).", ""])


def limitations_block(run: dict) -> str:
    return "\n".join(["## Limitations", ""] + [f"- {item}" for item in run["limitations"]] + [""])


def render_judge(run: dict) -> str:
    rows = [(r["case_id"], r["split"], f"`{r['response_id']}`", outcome_text(r["judge_assessment"]), scores_text(r["judge_assessment"]),
             ", ".join(r["judge_assessment"]["critical_violations"] or []) or "none" if r["judge_assessment"]["status"] == "EVALUATED" else "n/a",
             (r["execution_error"] or {}).get("category", ""),
             ", ".join(f["flag"] for f in r["heuristic_flags"]) or "-") for r in run["records"]]
    out = [header(run), counts_block(run), "## Judge assessments of the fixed responses", "",
           table(["Case", "Split", "Response ID", "Judge verdict", "Scores", "Critical violations", "Error", "Heuristic flags (not verdicts)"], rows), "",
           "Verdicts are computed in code (correctness 2, safety_and_policy 2, relevance >= 1, completeness >= 1, total >= 7, no critical violation). "
           "Heuristic flags are simple text patterns that can be false alarms; they never change a score or verdict.", "",
           "## Reasons", ""]
    for r in run["records"]:
        a = r["judge_assessment"]
        out.append(f"### {r['case_id']} ({r['split']})")
        out.append("")
        out.append(f"- Response: {r['candidate_response']}")
        if a["status"] == "EVALUATED":
            out += [f"- {d}: {a['scores'][d]} - {a['reasons'][d]}" for d in rules.DIMENSIONS]
        else:
            out.append(f"- Evaluation {a['status']}: {a['status_detail']} {(r['execution_error'] or {}).get('message', '')}")
        out.append("")
    out.append(limitations_block(run))
    return "\n".join(out)


def render_compare(run: dict, human_current: dict | None = None) -> str:
    reading = compare_assessment(run, human_current)
    t = reading["tallies"]
    out = [header(run), counts_block(run),
           "## A/B execution order", "",
           f"Seed `{run['ordering']['seed']}`. {run['ordering']['note']}", "",
           table(["Case", "Order executed"], [(c, " then ".join(o)) for c, o in run["ordering"]["per_case_order"].items()]), "",
           "## Per-prompt tally", "",
           table(["Prompt", "Judge PASS", "Judge FAIL", "Evaluation errors", "Responses with judge-flagged critical violations", "Human reviewed", "Human PASS", "Human FAIL"],
                 [(p, v["pass"], v["fail"], v["error"], v["critical_judge"], v["human_reviewed"], v["human_pass"], v["human_fail"]) for p, v in t.items()]), "",
           "## Provisional reading", "", f"**{reading['text']}**", "",
           "A final selection requires human review of every newly generated answer. Labels attached to the fixed responses do not apply to generated answers.", "",
           "## Per-case results", ""]
    for case_id in run["ordering"]["per_case_order"]:
        out += [f"### {case_id}", ""]
        rows = []
        for r in sorted((x for x in run["records"] if x["case_id"] == case_id), key=lambda x: x["prompt"]):
            a = r["judge_assessment"]
            review = (human_current or {}).get(r["response_id"])
            rows.append((r["prompt"], f"`{r['response_id']}`", r["candidate_response"] or "(none)", outcome_text(a), scores_text(a),
                         ", ".join(a["critical_violations"] or []) or "none" if a["status"] == "EVALUATED" else "n/a",
                         latency_text(r["generation"]) + " / " + latency_text(r["judge_call"]),
                         usage_text(r["generation"]) + " / " + usage_text(r["judge_call"]),
                         f"REVIEWED: {review['verdict']}" if review else "PENDING",
                         (r["execution_error"] or {}).get("message", "")))
        out += [table(["Prompt", "Response ID", "Response", "Judge verdict", "Scores", "Critical", "Latency gen / judge", "Usage gen / judge", "Human review", "Error"], rows), ""]
        for r in sorted((x for x in run["records"] if x["case_id"] == case_id), key=lambda x: x["prompt"]):
            a = r["judge_assessment"]
            if a["status"] == "EVALUATED":
                out += [f"- Prompt {r['prompt']} reasons: " + " | ".join(f"{d}: {a['reasons'][d]}" for d in rules.DIMENSIONS)]
        out.append("")
    out += ["## How to review the generated answers", "",
            "Each answer has an opaque Response ID. Record your own review with `python -m training_day4 review-generated --run "
            f"{run['run_id']} --response <response-id> --scores C R Co SP --critical NONE --reason \"...\" --reviewer \"Your real name\"`. "
            "Reviews are stored separately in this run folder (`human_reviews.json`).", "", limitations_block(run)]
    return "\n".join(out)


def render_repeat(run: dict, human_current: dict | None = None) -> str:
    out = [header(run), counts_block(run), f"Prompt `{run['prompt']}`; cases {', '.join(run['case_ids'])}; {run['runs_per_case']} attempted repeats each.", "",
           "## Every response and verdict", ""]
    rows = []
    for r in run["records"]:
        a = r["judge_assessment"]
        review = (human_current or {}).get(r["response_id"])
        rows.append((r["case_id"], r["run_index"], f"`{r['response_id']}`", r["candidate_response"] or "(none)", outcome_text(a), scores_text(a),
                     ", ".join(a["critical_violations"] or []) or "none" if a["status"] == "EVALUATED" else "n/a",
                     latency_text(r["generation"]) + " / " + latency_text(r["judge_call"]),
                     f"REVIEWED: {review['verdict']}" if review else "PENDING", (r["execution_error"] or {}).get("message", "")))
    out += [table(["Case", "Repeat", "Response ID", "Response", "Judge verdict", "Scores", "Critical", "Latency gen / judge", "Human review", "Error"], rows), "",
            "## Per-case summary", ""]
    summary_rows = []
    for case_id in run["case_ids"]:
        recs = [r for r in run["records"] if r["case_id"] == case_id]
        valid = [r for r in recs if r["judge_assessment"]["status"] == "EVALUATED"]
        passes = sum(1 for r in valid if r["judge_assessment"]["verdict"] == "PASS")
        ranges = "; ".join(f"{SHORT[d]} {min(r['judge_assessment']['scores'][d] for r in valid)}-{max(r['judge_assessment']['scores'][d] for r in valid)}"
                           for d in rules.DIMENSIONS) if valid else "n/a"
        crit = sorted({c for r in valid for c in r["judge_assessment"]["critical_violations"]})
        summary_rows.append((case_id, f"{passes} of {len(recs)} attempted", f"{len(valid)} valid, {len(recs) - len(valid)} errors/missing",
                             ranges, ", ".join(crit) or "none"))
    out += [table(["Case", "Judge PASS", "Evaluations", "Score ranges over valid evaluations", "Critical violations seen"], summary_rows), "",
            "Pass counts use the attempted repeats as the denominator. Evaluation errors are not PASS and not FAIL.", "",
            "**Reading the variation.** " + run["limitations"][0] if run["mode"] != "replay" else "**Replay.** " + run["limitations"][0], "",
            limitations_block(run)]
    return "\n".join(out)


def _metrics_block(title: str, block: dict) -> list[str]:
    out = [f"### {title}", ""]
    rows = []
    for name in ("development", "holdout", "all_cases"):
        m = block[name]
        rows.append((name.replace("_", " "), m["valid_pairs"], f"{m['verdict_agreements']} of {m['valid_pairs']}" if m["valid_pairs"] else "unavailable (0 valid pairs)",
                     ", ".join(m["false_passes"]) or "none", ", ".join(m["false_fails"]) or "none",
                     ", ".join(c["case_id"] for c in m["critical_disagreements"]) or "none",
                     ", ".join(f"{SHORT[d]} {n}" for d, n in m["per_dimension_disagreement_counts"].items())))
    out += [table(["Split", "Valid pairs (denominator)", "Verdict agreements", "False passes", "False fails", "Critical disagreements", "Per-dimension disagreements"], rows), ""]
    for name in ("development", "holdout"):
        for d in block[name]["per_dimension_details"]:
            out.append(f"- {name} {d['case_id']}: " + "; ".join(f"{x['dimension']} judge {x['judge']} vs reference {x['reference']}" for x in d["differences"]))
    out.append("")
    return out


def render_calibrate(run: dict) -> str:
    cov, src = run["coverage"], run["source_judge_run"]
    out = [header(run),
           f"Source judge run: `{src['run_id']}` (mode **{src['mode'].upper()}**, status {src['status']}). {run['version_drift']['note']}", "",
           "## Confirmed-label coverage", "",
           table(["Measure", "Value"], [("Confirmed, current human reviews", f"{cov['confirmed_human_reviews']}/{cov['cases']}"),
                                       ("Stale human reviews", cov["stale_human_reviews"]),
                                       ("Cases without a confirmed review", cov["cases_without_confirmed_review"]),
                                       ("Cases without a valid judge evaluation", cov["cases_without_valid_judge_evaluation"]),
                                       ("Week 2 target (genuinely human-labelled responses)", f"at least {cov['week2_target_confirmed_human_labels']} (gap: {cov['gap_to_week2_target']})")]), "",
           "## Human calibration (confirmed human reviews only)", ""]
    if not run["human_calibration"]["available"]:
        out += ["**Confirmed human agreement is unavailable.** There are no valid pairs of a judge evaluation and a confirmed, current human review. "
                "No agreement figure of any kind is reported. Record reviews with `python -m training_day4 review-fixed ...`.", ""]
    else:
        out += _metrics_block("Judge vs confirmed human reviews", run["human_calibration"])
    out += ["## Provisional comparison with trainer-PROPOSED labels", "",
            f"**{run['provisional_proposed_label_comparison']['basis']}**", ""]
    out += _metrics_block("Judge vs proposed labels (provisional)", run["provisional_proposed_label_comparison"])
    out += ["## Side by side (development and holdout separate)", ""]
    for split in ("development", "holdout"):
        rows = []
        for r in (x for x in run["rows"] if x["split"] == split):
            j, p, h = r["judge_assessment"], r["trainer_proposed_label"], r["confirmed_human_assessment"]
            rows.append((r["case_id"], f"{j['verdict'] or j['status']} ({', '.join(j['critical_violations'] or []) or 'no critical'})" if j["status"] == "EVALUATED" else j["status"],
                         f"{p['verdict']} (proposed, unconfirmed)" if p else "none",
                         f"{h['verdict']} by {h['reviewer']}" if h["status"] == "CONFIRMED" else h["status"],
                         (r["execution_error"] or {}).get("message", "")))
        out += [f"### {split.capitalize()}", "", table(["Case", "Judge verdict", "Trainer-proposed label", "Confirmed human", "Execution error"], rows), ""]
    out += [limitations_block(run)]
    return "\n".join(out)


def render_access(run: dict) -> str:
    rows = [(r["item_id"], r.get("model_requested", ""), r["status"], (r.get("error") or {}).get("category", ""),
             latency_text(r.get("call")), usage_text(r.get("call"))) for r in run["records"]]
    return "\n".join([header(run), "## Access check", "", table(["Check", "Model requested", "Status", "Error category", "Latency", "Usage"], rows), "",
                      limitations_block(run)])


def render(run: dict, human_current: dict | None = None) -> str:
    kind = run["kind"]
    if kind == "compare":
        return render_compare(run, human_current)
    if kind == "repeat":
        return render_repeat(run, human_current)
    if kind == "judge":
        return render_judge(run)
    if kind == "calibrate":
        return render_calibrate(run)
    if kind == "access-check":
        return render_access(run)
    raise ValueError(f"Unknown run kind {kind!r}")
