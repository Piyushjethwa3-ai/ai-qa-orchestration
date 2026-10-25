"""
Run labelled cases through the retriever and score them.

The retriever is called with the query, the OS and top-k ONLY. Labels are used afterwards,
by metrics.py, and by the drop-required fault in faults.py (which says so).
"""

from training_day5 import faults, metrics
from training_day5.knowledge import Corpus
from training_day5.retriever import RETRIEVER_VERSION, retrieve

EVALUATOR_VERSION = "day5-eval-v1"


def _fault_summary(name, per_case: list[dict]) -> dict:
    if name is None:
        return {"mode": "none", "label": None, "status": "NONE", "applied_cases": [], "not_applied_cases": [],
                "note": "No fault was injected. This is the normal retrieval evaluation."}
    applied = [r["case_id"] for r in per_case if r["fault"]["applied"]]
    not_applied = [r["case_id"] for r in per_case if not r["fault"]["applied"]]
    status = "APPLIED" if applied and not not_applied else ("NOT APPLIED" if not applied else "PARTIALLY APPLIED")
    note = ("The fault was applied to every selected case." if status == "APPLIED" else
            "The fault's precondition was absent in every selected case. NOT APPLIED: no fault demonstration can be claimed."
            if status == "NOT APPLIED" else
            "The fault was applied to some selected cases only; the others are marked NOT APPLIED.")
    return {"mode": name, "label": faults.SYNTHETIC_LABEL, "status": status, "applied_cases": applied,
            "not_applied_cases": not_applied, "note": note}


def run_evaluation(cases: list[dict], corpus: Corpus, top_k: int, fault: str | None = None, retrieve_fn=retrieve) -> dict:
    """Evaluate the given cases. `fault` is None or one of faults.FAULTS and affects only this call."""
    if fault is not None and fault not in faults.FAULTS:
        raise ValueError(f"Unknown fault {fault!r}. Allowed: {', '.join(faults.FAULTS)}")
    per_case = []
    for case in cases:
        # Only the query, the OS and top-k go to the retriever.
        result = retrieve_fn(query=case["query"], os=case["os"], top_k=top_k, corpus=corpus)
        hits = [h.to_dict() for h in result.hits]
        outcome = faults.apply_fault(fault, hits, corpus, top_k, case["expected_doc_ids"])
        retrieved_ids = [h["doc_id"] for h in outcome.hits]
        scored = metrics.score_case(case["answerable"], case["expected_doc_ids"], case["prohibited_doc_ids"], retrieved_ids)
        per_case.append({
            "case_id": case["case_id"], "query": case["query"], "os": case["os"], "os_normalised": result.os_normalised,
            "os_note": result.os_note, "answerable": case["answerable"],
            "expected_doc_ids": list(case["expected_doc_ids"]), "prohibited_doc_ids": list(case["prohibited_doc_ids"]),
            "retrieved": outcome.hits, "retrieved_ids": retrieved_ids, **scored,
            "fault": {"mode": fault or "none", "applied": outcome.applied,
                      "status": ("NONE" if fault is None else "APPLIED" if outcome.applied else "NOT APPLIED"),
                      "detail": outcome.detail},
        })
    return {"retriever_version": RETRIEVER_VERSION, "evaluator_version": EVALUATOR_VERSION, "top_k": top_k,
            "fault": _fault_summary(fault, per_case), "results": per_case, "aggregates": metrics.aggregate(per_case)}
