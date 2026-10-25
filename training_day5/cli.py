"""
Command-line interface: `python -m training_day5 <command>`.

  validate | list-docs | show-doc --id ID | show-case --id ID
  retrieve --case ID [--top-k N]   or   retrieve --query TEXT [--os OS] [--top-k N]
  evaluate --cases all|IDs [--top-k N] [--fault obsolete-first|wrong-os|drop-required]
  summary --run latest|RUN-ID

Everything is local and deterministic; nothing calls a model or the network.
evaluate exit codes: 0 completed and every selected case passed; 1 completed and at least one
case failed (results are still saved); 2 invalid input or an execution error.
Other commands: 0 fine, 2 invalid input.
"""

import argparse
import sys

from training_day5 import cases as cases_module
from training_day5 import evaluate, faults, knowledge, metrics, paths, report, retriever, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m training_day5", description="Day 5: local document retrieval and retrieval evaluation.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Check the knowledge base, manifest, cases and policy file.")
    sub.add_parser("list-docs", help="List the knowledge-base documents and their metadata.")
    show_doc = sub.add_parser("show-doc", help="Show one document: metadata and Markdown content.")
    show_doc.add_argument("--id", required=True)
    show_case = sub.add_parser("show-case", help="Show one labelled retrieval case.")
    show_case.add_argument("--id", required=True)

    retrieve = sub.add_parser("retrieve", help="Run the retriever for a case or a free query.")
    group = retrieve.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="Load the query and OS from this case. Labels are not passed to the retriever.")
    group.add_argument("--query")
    retrieve.add_argument("--os", default=None, help="macos, windows or any (with --query). Default: any.")
    retrieve.add_argument("--top-k", type=int, default=3)

    evaluate_cmd = sub.add_parser("evaluate", help="Evaluate retrieval against the labelled cases and save a report.")
    evaluate_cmd.add_argument("--cases", nargs="+", default=["all"], help="'all' or case IDs, e.g. R01 R07")
    evaluate_cmd.add_argument("--top-k", type=int, default=3)
    evaluate_cmd.add_argument("--fault", choices=faults.FAULTS, default=None,
                              help="SYNTHETIC fault injection for this command only (off by default).")

    summary_cmd = sub.add_parser("summary", help="Show a saved evaluation.")
    summary_cmd.add_argument("--run", default="latest", help="'latest' or a run ID")
    return parser


def _fail(message: str) -> int:
    print(f"Refused: {message}", file=sys.stderr)
    return 2


def _load_all():
    """Load and check corpus and cases. Returns (corpus, cases_doc) or raises."""
    corpus = knowledge.load_corpus()
    doc = cases_module.load_cases_doc()
    problems = cases_module.inspect_cases(doc, {d.doc_id for d in corpus.documents},
                                          {d.doc_id for d in corpus.documents if d.status == "obsolete"})
    if problems:
        raise cases_module.CaseError("; ".join(problems))
    return corpus, doc


def cmd_validate(_args) -> int:
    problems, corpus = knowledge.inspect_corpus()
    out_problems = list(problems)
    if corpus is not None:
        doc = None
        try:
            doc = cases_module.load_cases_doc()
            out_problems += cases_module.inspect_cases(doc, {d.doc_id for d in corpus.documents},
                                                       {d.doc_id for d in corpus.documents if d.status == "obsolete"})
        except cases_module.CaseError as exc:
            out_problems.append(str(exc))
        policy = paths.POLICY_PATH
        if not policy.exists():
            out_problems.append(f"Missing retrieval policy: {paths.display(policy)}")
        else:
            kb_root = paths.KB_DIR.resolve()
            if kb_root == policy.resolve() or kb_root in policy.resolve().parents:
                out_problems.append("The retrieval policy must live outside the knowledge folder so it is never indexed as support knowledge.")
            if any((kb_root / d.path).resolve() == policy.resolve() for d in corpus.documents):
                out_problems.append("The retrieval policy is listed in the manifest; it must not be indexed.")
    if out_problems:
        for problem in out_problems:
            print(f"PROBLEM: {problem}")
        print(f"Day 5 data INVALID: {len(out_problems)} problem(s).")
        return 2
    approved = sum(1 for d in corpus.documents if d.status == "approved")
    answerable = sum(1 for c in doc["cases"] if c["answerable"])
    print(f"Knowledge base valid: {len(corpus.documents)} documents ({approved} approved, {len(corpus.documents) - approved} obsolete)")
    print(f"Manifest hash {corpus.manifest_sha256[:16]}…   knowledge-base hash {corpus.knowledge_base_sha256[:16]}…")
    print(f"Cases valid: {len(doc['cases'])} ({answerable} answerable, {len(doc['cases']) - answerable} unanswerable), dataset {doc.get('dataset_version')}")
    print(f"Retrieval policy present and not indexed: {paths.display(paths.POLICY_PATH)}")
    return 0


def cmd_list_docs(_args) -> int:
    try:
        corpus = knowledge.load_corpus()
    except knowledge.KnowledgeError as exc:
        return _fail(f"the knowledge base is invalid: {exc}")
    print(f"{'doc_id':<22}{'os':<9}{'status':<10}{'ver':<5}{'topic':<20}{'supersedes':<20}path")
    for d in corpus.documents:
        print(f"{d.doc_id:<22}{d.os:<9}{d.status:<10}{d.version:<5}{d.topic:<20}{d.supersedes or '-':<20}{d.path}")
    return 0


def cmd_show_doc(args) -> int:
    try:
        corpus = knowledge.load_corpus()
    except knowledge.KnowledgeError as exc:
        return _fail(f"the knowledge base is invalid: {exc}")
    doc = corpus.get(args.id)
    if doc is None:
        return _fail(f"unknown document {args.id!r}. Known documents: {', '.join(d.doc_id for d in corpus.documents)}")
    print(f"{doc.doc_id}  [{doc.status}, os={doc.os}, version {doc.version}, topic {doc.topic}, supersedes {doc.supersedes or 'nothing'}]")
    print(f"File: knowledge/day5/{doc.path}   content sha256 {doc.content_sha256[:16]}…\n")
    print(doc.content)
    return 0


def _case_by_id(case_id: str):
    corpus, doc = _load_all()
    case = next((c for c in doc["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise cases_module.CaseError(f"unknown case {case_id!r}. Known cases: {', '.join(c['case_id'] for c in doc['cases'])}")
    return corpus, case


def cmd_show_case(args) -> int:
    try:
        _, case = _case_by_id(args.id)
    except (cases_module.CaseError, knowledge.KnowledgeError) as exc:
        return _fail(str(exc))
    print(f"=== {case['case_id']}  answerable: {case['answerable']}  os: {case['os']}")
    print(f"Query: {case['query']}")
    print(f"Expected documents (label): {', '.join(case['expected_doc_ids']) or '(none: nothing should be retrieved)'}")
    print(f"Prohibited documents (label): {', '.join(case['prohibited_doc_ids'])}")
    print(f"Expected behaviour: {case['expected_behaviour']}")
    print(f"Rationale: {case['rationale']}")
    print("These labels are the answer key. The retriever never sees them.")
    return 0


def cmd_retrieve(args) -> int:
    try:
        if args.case:
            if args.os is not None:
                return _fail("--os cannot be combined with --case; the OS comes from the case.")
            corpus, case = _case_by_id(args.case)
            query, os_value = case["query"], case["os"]  # ONLY these two, plus top-k, reach the retriever
        else:
            corpus, query, os_value = knowledge.load_corpus(), args.query, (args.os or "any")
        result = retriever.retrieve(query=query, os=os_value, top_k=args.top_k, corpus=corpus)
    except (cases_module.CaseError, knowledge.KnowledgeError, retriever.RetrievalError) as exc:
        return _fail(str(exc))
    print(f"Query: {result.query}")
    print(f"OS: {result.os_input!r} -> {result.os_normalised} ({result.os_note})   top-k {result.top_k}")
    print(f"Considered {result.candidate_count} document(s); {result.excluded_count} excluded by status/OS filtering.")
    print(f"Query terms: {', '.join(result.query_terms) or '(none)'}")
    if not result.hits:
        print("No documents retrieved: no eligible document has a positive lexical score.")
    for hit in result.hits:
        print(f"  {hit.rank}. {hit.doc_id}   lexical score {hit.score}   matched: {', '.join(hit.matched_terms)}")
    print("Lexical scores are word-overlap counts, not confidence probabilities. A positive score does not prove a document answers the question.")
    return 0


def cmd_evaluate(args) -> int:
    try:
        retriever.validate_top_k(args.top_k)
        corpus, doc = _load_all()
        selected = cases_module.select_cases(doc, args.cases)
        evaluation = evaluate.run_evaluation(selected, corpus, args.top_k, args.fault)
        run = report.build_run(evaluation, corpus, [c["case_id"] for c in selected], paths.CASES_PATH, doc)
        run_dir, written = report.save_run(run, report.render_markdown(run))
    except (cases_module.CaseError, knowledge.KnowledgeError, retriever.RetrievalError, report.RunExistsError, ValueError, OSError) as exc:
        return _fail(f"{exc}")
    agg, fault = run["aggregates"], run["fault"]
    if run["label"]:
        print(f"*** {run['label']}: {fault['mode']} - fault {fault['status']} ***")
        print(f"    {fault['note']}")
    print(f"Run ID: {run['run_id']}   mode {run['mode']}   top-k {run['top_k']}")
    print(f"Cases passed {agg['passed']} of {agg['cases']}; failed: {', '.join(agg['failed_case_ids']) or 'none'}")
    print(f"Macro precision (answerable only) {metrics.display(agg['macro_precision'])}   macro recall {metrics.display(agg['macro_recall'])}   "
          f"unanswerable passed {agg['unanswerable_passed']} of {agg['unanswerable_cases']}   prohibited-document failures {agg['prohibited_failure_count']}")
    for r in run["results"]:
        print(f"  {r['case_id']}: {r['result']:<5} P {metrics.display(r['precision'])}  R {metrics.display(r['recall'])}  retrieved {', '.join(r['retrieved_ids']) or '(nothing)'}"
              + (f"  [fault {r['fault']['status']}]" if run["label"] else ""))
    for path in written:
        print(f"Report: {paths.display(path)}")
    return 0 if agg["failed"] == 0 else 1


def cmd_summary(args) -> int:
    try:
        run = summary.resolve(args.run)
    except summary.SummaryError as exc:
        return _fail(str(exc))
    print(summary.render(run))
    return 0


COMMANDS = {"validate": cmd_validate, "list-docs": cmd_list_docs, "show-doc": cmd_show_doc, "show-case": cmd_show_case,
            "retrieve": cmd_retrieve, "evaluate": cmd_evaluate, "summary": cmd_summary}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
