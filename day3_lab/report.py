"""
Writes run evidence: run.json (machine-readable), run.html (a static,
readable view of the same data) and, for the clinic, clinic_notes.md.

A new run never overwrites an earlier one. If --out already holds run
files, the command stops and asks for a fresh folder. Only `review`
updates an existing run.json, and it keeps every earlier review in a
history list.
"""

import json
import os
from html import escape
from pathlib import Path

from day3_lab.assessment import current_assessment
from day3_lab.dataset import DIMENSIONS

RUN_FILES = ("run.json", "run.html", "clinic_notes.md")


class OutputExistsError(FileExistsError):
    pass


def ensure_fresh_output_dir(out_dir: Path) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise OutputExistsError(f"{out_dir} exists and is not a folder. Choose a fresh output directory.")
    existing = [name for name in RUN_FILES if (out_dir / name).exists()]
    if existing:
        raise OutputExistsError(
            f"{out_dir} already contains an earlier run ({', '.join(existing)}). It was left untouched. "
            f"Choose a fresh output directory, for example {out_dir}-2, and use that path in later "
            "open/review commands."
        )


def write_new_run(out_dir: Path, run: dict) -> list[Path]:
    """Write a brand-new run. Uses exclusive-create mode so nothing is ever overwritten."""
    ensure_fresh_output_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"run.json": json.dumps(run, indent=2, ensure_ascii=False) + "\n", "run.html": render_html(run, (out_dir / "run.json").as_posix())}
    if run["kind"] == "clinic":
        files["clinic_notes.md"] = render_clinic_notes(run)
    written = []
    for name, content in files.items():
        with open(out_dir / name, "x", encoding="utf-8") as handle:
            handle.write(content)
        written.append(out_dir / name)
    return written


def load_run(report_path: Path) -> dict:
    with open(report_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _replace_file(path: Path, content: str) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temp_path, path)  # atomic: readers never see a half-written file


def save_reviewed_run(report_path: Path, run: dict) -> Path:
    """Rewrite run.json after a review, then regenerate run.html beside it."""
    _replace_file(report_path, json.dumps(run, indent=2, ensure_ascii=False) + "\n")
    html_path = report_path.with_name("run.html")
    _replace_file(html_path, render_html(run, report_path.as_posix()))
    return html_path


# ---------------------------------------------------------------- HTML

_CSS = """
:root { --bg:#ffffff; --fg:#1d1f23; --muted:#5b616e; --line:#d9dce3; --panel:#f5f6f8;
  --pass:#1a7f37; --fail:#c62828; --pending:#9a6700; --error:#8250df; --mock:#0b5cad; }
@media (prefers-color-scheme: dark) { :root { --bg:#14161a; --fg:#e6e8eb; --muted:#9aa1ad;
  --line:#2d323b; --panel:#1c1f25; --pass:#4ac26b; --fail:#ff7b72; --pending:#d4a72c;
  --error:#c297ff; --mock:#6cb6ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:1040px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:19px; margin:32px 0 8px; }
h3 { font-size:15px; margin:16px 0 6px; }
.banner { border:2px solid var(--mock); border-radius:8px; padding:10px 14px; margin:12px 0;
  font-weight:600; }
.banner.live { border-color:var(--error); }
table { border-collapse:collapse; width:100%; margin:6px 0; }
th, td { text-align:left; vertical-align:top; padding:6px 8px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; width:200px; }
pre { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px;
  overflow-x:auto; white-space:pre-wrap; word-break:break-word; margin:6px 0; font-size:13px; }
code { font-size:13px; }
.record { border:1px solid var(--line); border-radius:10px; padding:4px 16px 12px; margin:20px 0; }
.badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:700;
  border:1px solid currentColor; margin-right:4px; }
.PASS { color:var(--pass); } .FAIL { color:var(--fail); } .REVIEW_PENDING, .PENDING, .STALE { color:var(--pending); }
.ERROR, .NOT_RUN { color:var(--error); } .MOCK { color:var(--mock); } .LIVE { color:var(--error); }
.muted { color:var(--muted); } ul { margin:4px 0; padding-left:20px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:8px; }
.cell { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:8px; }
"""


def _badge(value) -> str:
    text = "null" if value is None else str(value)
    return f'<span class="badge {escape(text)}">{escape(text)}</span>'


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{escape(str(k))}</th><td>{v}</td></tr>" for k, v in pairs)


def _text(value) -> str:
    return "<span class='muted'>null</span>" if value is None else escape(str(value))


def _list(items) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def _human_status(record: dict) -> str:
    human = record["human_assessment"]
    if human.get("current") and current_assessment(record) is None:
        return "STALE"
    return human["status"]


def _render_assessment(record: dict, run: dict, report_hint: str) -> str:
    human = record["human_assessment"]
    assessment = current_assessment(record)
    parts = [f"<h3>Human assessment {_badge(_human_status(record))}</h3>"]
    if assessment:
        scores = "".join(
            f"<div class='cell'><div class='muted'>{d}</div><b>{assessment['scores'][d]}</b> / 2</div>"
            for d in DIMENSIONS
        )
        parts.append(f"<div class='grid'>{scores}<div class='cell'><div class='muted'>critical</div>"
                     f"<b>{'yes' if assessment['critical'] else 'no'}</b></div></div>")
        parts.append("<table>" + _rows([
            ("note", escape(assessment["note"])),
            ("reviewer", escape(f"{assessment['reviewer']} ({assessment['reviewer_source']})")),
            ("reviewed at", escape(assessment["reviewed_at"])),
            ("bound to response hash", f"<code>{escape(assessment['response_hash'])}</code>"),
        ]) + "</table>")
    elif record["provider"]["status"] == "ERROR":
        parts.append("<p class='muted'>Not reviewable: the provider returned an error.</p>")
    else:
        parts.append(
            "<p>No human assessment yet. Read the response against the approved context and rubric, "
            "then enter <b>your own</b> scores (correctness, relevance, completeness, safety):</p>"
            f"<pre>python -m day3_lab review --report {escape(report_hint)} --case "
            f"{escape(record['record_id'])} --scores C R Co S --critical yes|no --note \"your reason\"</pre>"
        )
    if len(human["history"]) > 1 or (human["history"] and not assessment):
        rows = "".join(
            f"<tr><td>{escape(h['reviewed_at'])}</td><td>{escape(h['reviewer'])}</td>"
            f"<td>{' '.join(str(h['scores'][d]) for d in DIMENSIONS)}</td>"
            f"<td>{'yes' if h['critical'] else 'no'}</td><td>{escape(h['note'])}</td>"
            f"<td><code>{escape(h['response_hash'][:12])}</code></td></tr>"
            for h in human["history"]
        )
        parts.append("<h3>Review history</h3><table><tr><th>when</th><th>reviewer</th><th>scores C R Co S</th>"
                     f"<th>critical</th><th>note</th><th>hash</th></tr>{rows}</table>")
    return "".join(parts)


def _render_record(record: dict, run: dict, report_hint: str) -> str:
    case = record["case"]
    context = case["approved_context"]
    provider = record["provider"]
    outcome = record["outcome"]
    out = [f"<section class='record' id='{escape(record['record_id'])}'>"]
    out.append(f"<h2>{escape(record['record_id'])} {_badge(record['source'])} {_badge(outcome['result'])}</h2>")
    out.append(f"<p><b>Outcome:</b> {_badge(outcome['result'])} {escape(outcome['reason'])}</p>")

    clinic = record.get("clinic")
    if clinic:
        expectation = clinic["teaching_expectation"]
        out.append("<h3>Clinic fixture</h3><table>" + _rows([
            ("label", f"<b>{escape(clinic['label'])}</b>"),
            ("purpose", escape(clinic["purpose"])),
            ("corrects", _text(clinic.get("corrects"))),
            ("teaching expectation", escape(
                f"structure {expectation['structure']}; human {expectation['human']}; "
                f"critical {expectation['critical']}. {expectation['why']}")),
            ("status of that expectation", escape(clinic["teaching_expectation_status"])),
        ]) + "</table>")

    out.append("<h3>Case and approved context</h3><table>" + _rows([
        ("case", escape(f"{case['case_id']} - {case['category']}")),
        ("question", escape(case["question"])),
        ("device", _text(context["device"])),
        ("context service_status", _text(context["service_status"])),
        ("context recovery_time", _text(context["recovery_time"])),
        ("guidance", escape(context["guidance"])),
        ("expected behaviour", _list(case["expected_behaviour"])),
        ("prohibited behaviour", _list(case["prohibited_behaviour"])),
        ("requirement IDs", escape(", ".join(case["requirement_ids"]))),
    ]) + "</table>")

    error = provider.get("error")
    out.append("<h3>Provider</h3><table>" + _rows([
        ("mode / status", _badge(provider["mode"]) + _badge(provider["status"])),
        ("model", _text(provider.get("model"))),
        ("error", _text(f"{error['category']}: {error['message']}" if error else None)),
        ("token usage", _text(json.dumps(provider["token_usage"]) if provider.get("token_usage") else None)),
        ("elapsed ms", _text(provider.get("elapsed_ms")) + (
            f" <span class='muted'>({escape(provider['elapsed_note'])})</span>" if provider.get("elapsed_note") else "")),
    ]) + "</table>")

    out.append("<h3>Raw response (evidence, unmodified)</h3>")
    out.append(f"<pre>{_text(record['raw_response'])}</pre>")
    structural = record["structural"]
    findings = structural["findings"]
    out.append(f"<h3>Structural check {_badge(structural['result'])}</h3>")
    out.append("<p class='muted'>Structure only: JSON, exact keys, types and allowed status values. "
               "It does not check that the answer matches the approved context.</p>")
    if findings:
        out.append("<table><tr><th>stage</th><th>path</th><th>message</th></tr>" + "".join(
            f"<tr><td>{escape(f['stage'])}</td><td>{escape(f['path'])}</td><td>{escape(f['message'])}</td></tr>"
            for f in findings) + "</table>")
    out.append(f"<p class='muted'>Response hash: <code>{_text(record['response_hash'])}</code></p>")

    check = record.get("exact_string_check")
    if check:
        out.append(f"<h3>Naive exact-string comparison {_badge(check['result'])} (diagnostic only)</h3>")
        out.append("<table>" + _rows([
            ("reference", escape(check["reference"])),
            ("actual", escape(check["actual"])),
            ("status", f"<b>{escape(check['status'])}</b>"),
            ("why it misleads", escape(check["why_it_misleads"])),
        ]) + "</table>")

    out.append(_render_assessment(record, run, report_hint))
    out.append("</section>")
    return "".join(out)


def render_html(run: dict, report_hint: str | None = None) -> str:
    report_hint = report_hint or "<path-to>/run.json"
    mode = run["provider_mode"]
    summary = run["summary"]
    rubric = run["rubric"]
    git = run["git"]
    title = "Day 3 failure clinic" if run["kind"] == "clinic" else "Day 3 response evaluation"
    scale_rows = "".join(
        f"<tr><th>{escape(d)}</th>" + "".join(f"<td><b>{s}</b> {escape(rubric['scales'][d][s])}</td>"
                                               for s in ("0", "1", "2")) + "</tr>"
        for d in DIMENSIONS
    )
    counts = " &nbsp; ".join(
        f"{escape(group)}: " + ", ".join(f"{_badge(k)}{v}" for k, v in sorted(values.items()))
        for group, values in summary.items() if isinstance(values, dict)
    )
    body = [
        f"<h1>{escape(title)}</h1>",
        f"<p class='muted'>Run {escape(run['run_id'])} &middot; {escape(run['created_at'])}</p>",
        f"<div class='banner {'live' if mode == 'LIVE' else ''}'>{_badge(mode)} {escape(run['disclaimer'])}</div>",
        "<table>" + _rows([
            ("records", str(summary["records"])),
            ("counts", counts),
            ("variant", _text(run.get("variant"))),
            ("model", _text(run.get("model"))),
            ("git commit", _text(git["commit"]) + f" &middot; dirty: {_text(git['dirty'])}"),
            ("prompt", escape(f"{run['prompt']['path']}  sha256 {run['prompt']['sha256'][:16]}…")),
            ("dataset", escape(f"{run['dataset']['path']}  {run['dataset']['version']}  "
                               f"sha256 {run['dataset']['sha256'][:16]}…")),
            ("rubric", escape(f"{rubric['path']}  {rubric['version']}  sha256 {rubric['sha256'][:16]}…")),
            ("decision rule", escape(rubric["decision_rule"])),
        ]) + "</table>",
        "<h2>Rubric</h2><table><tr><th>dimension</th><th>0</th><th>1</th><th>2</th></tr>"
        f"{scale_rows}</table>",
    ]
    body.extend(_render_record(record, run, report_hint) for record in run["records"])
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>\n"
    )


# ------------------------------------------------------- clinic notes

def render_clinic_notes(run: dict) -> str:
    lines = [
        f"# Day 3 failure clinic notes ({run.get('variant')} variant)",
        "",
        f"Run `{run['run_id']}`, created {run['created_at']}.",
        "",
        f"> {run['disclaimer']}",
        "",
        "The teaching expectations below are the trainer's lesson plan for discussion. They are",
        "**not** human reviews and are not recorded as such. Every record starts with human",
        "assessment PENDING. Enter your own scores with `python -m day3_lab review ...`.",
        "",
    ]
    for record in run["records"]:
        clinic = record["clinic"]
        expectation = clinic["teaching_expectation"]
        parsed = record["parsed_response"] or {}
        lines += [
            f"## {record['record_id']} ({clinic['label']})",
            "",
            f"- Case: {record['case_id']}, \"{record['case']['question']}\"",
            f"- Approved context: service_status `{record['case']['approved_context']['service_status']}`, "
            f"recovery_time `{record['case']['approved_context']['recovery_time']}`",
            f"- Purpose: {clinic['purpose']}",
        ]
        if clinic.get("corrects"):
            lines.append(f"- Corrects: `{clinic['corrects']}`. The original stays in the first clinic run.")
        lines += [
            f"- Response answer: \"{parsed.get('answer')}\"",
            f"- Response recovery_time: `{parsed.get('recovery_time')}`",
            f"- Structural check (actual): **{record['structural']['result']}**",
            f"- Human assessment (actual): **{record['human_assessment']['status']}**",
            f"- Outcome (actual): **{record['outcome']['result']}**: {record['outcome']['reason']}",
        ]
        check = record.get("exact_string_check")
        if check:
            lines.append(f"- Naive exact-string comparison: **{check['result']}**. {check['status']}")
        lines += [
            f"- Teaching expectation (not a review): structure {expectation['structure']}, "
            f"human {expectation['human']}, critical {expectation['critical']}.",
            f"- Discussion point: {expectation['why']}",
            "",
        ]
    return "\n".join(lines)
