"""
Retrieval metrics. The scoring unit is the DOCUMENT ID: a document counts once if it was
returned, whatever its rank, and there is no partial credit within a document.

ANSWERABLE cases (expected documents exist):
    precision = relevant retrieved / actual retrieved count      (0 when nothing was returned)
    recall    = relevant retrieved / expected count
    PASS only when recall = 1 AND no prohibited document was returned.
    Extra irrelevant results lower precision but do not fail this classroom gate by themselves.

UNANSWERABLE cases (no document can answer the question):
    precision and recall are N/A (stored as null).
    PASS only when zero documents were returned. A non-empty result means the retrieval
    abstention expectation failed. That is NOT proof that a model would hallucinate.

Aggregates: macro precision and recall are the plain means over ANSWERABLE cases only.
Unanswerable successes and prohibited-document failures are reported separately.
"""

GATE_EXPLANATION = (
    "Classroom gate (document IDs are the unit). Answerable case: PASS requires recall = 1 and no prohibited "
    "document in the results; extra irrelevant documents only reduce precision. Unanswerable case: PASS requires "
    "that nothing is retrieved; precision and recall are N/A. Macro precision and recall average the answerable "
    "cases only. Unanswerable successes and prohibited-document failures are counted separately. This is a "
    "classroom gate, not a release decision."
)


def display(value) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def score_case(answerable: bool, expected: list[str], prohibited: list[str], retrieved: list[str]) -> dict:
    retrieved_unique = list(dict.fromkeys(retrieved))
    relevant = [d for d in retrieved_unique if d in expected]
    missing = [d for d in expected if d not in retrieved_unique]
    prohibited_hits = [d for d in retrieved_unique if d in prohibited]
    if answerable:
        precision = (len(relevant) / len(retrieved_unique)) if retrieved_unique else 0.0
        recall = len(relevant) / len(expected)
        passed = recall == 1 and not prohibited_hits
        parts = []
        if missing:
            parts.append(f"missing expected document(s) {', '.join(missing)} (recall {recall:.3f})")
        if prohibited_hits:
            parts.append(f"returned prohibited document(s) {', '.join(prohibited_hits)}")
        explanation = ("Every expected document was retrieved and no prohibited document was returned." if passed
                       else "Failed: " + "; ".join(parts) + ".")
        if passed and len(retrieved_unique) > len(relevant):
            explanation += f" {len(retrieved_unique) - len(relevant)} extra document(s) lowered precision to {precision:.3f}."
    else:
        precision = recall = None
        passed = not retrieved_unique
        explanation = ("No documents were retrieved, which meets the abstention expectation." if passed else
                       f"Failed: {len(retrieved_unique)} document(s) were retrieved ({', '.join(retrieved_unique)}) for a question "
                       "the knowledge base cannot answer. This is a retrieval abstention failure, not proof of model hallucination.")
        if prohibited_hits:
            explanation += f" Prohibited document(s) returned: {', '.join(prohibited_hits)}."
    return {"relevant_retrieved_ids": relevant, "missing_ids": missing, "prohibited_matches": prohibited_hits,
            "precision": precision, "recall": recall, "result": "PASS" if passed else "FAIL", "explanation": explanation}


def aggregate(results: list[dict]) -> dict:
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    mean = lambda values: (sum(values) / len(values)) if values else None
    return {
        "cases": len(results),
        "passed": sum(1 for r in results if r["result"] == "PASS"),
        "failed": sum(1 for r in results if r["result"] == "FAIL"),
        "failed_case_ids": [r["case_id"] for r in results if r["result"] == "FAIL"],
        "answerable_cases": len(answerable),
        "answerable_passed": sum(1 for r in answerable if r["result"] == "PASS"),
        "macro_precision": mean([r["precision"] for r in answerable]),
        "macro_recall": mean([r["recall"] for r in answerable]),
        "unanswerable_cases": len(unanswerable),
        "unanswerable_passed": sum(1 for r in unanswerable if r["result"] == "PASS"),
        "prohibited_failure_cases": [r["case_id"] for r in results if r["prohibited_matches"]],
        "prohibited_failure_count": sum(1 for r in results if r["prohibited_matches"]),
        "gate_explanation": GATE_EXPLANATION,
    }
