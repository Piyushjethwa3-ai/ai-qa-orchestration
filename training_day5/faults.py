"""
Synthetic fault injection for the failure clinic. EVERY FAULT IS OFF BY DEFAULT.

A fault is chosen per evaluate command (--fault NAME), is applied to the in-memory
results of that command only, and is never stored: no document is changed and no
setting persists. Nothing here keeps module-level state.

obsolete-first   If the results contain a positively scored CURRENT device-specific VPN guide,
                 put its obsolete counterpart at rank 1 (respecting top-k).
wrong-os         Replace a selected CURRENT device-specific VPN guide with the opposite OS's
                 current VPN guide.
drop-required    Evaluation harness only: after normal retrieval, remove one expected document
                 that was retrieved, in the case's expected order. This deliberately uses the
                 labels, so it lives here and never in the retriever.

If a fault's precondition is absent it is NOT APPLIED, and nothing may be claimed from it.
"""

from dataclasses import dataclass
from types import MappingProxyType

from training_day5.knowledge import Corpus

FAULTS = ("obsolete-first", "wrong-os", "drop-required")
SYNTHETIC_LABEL = "SYNTHETIC FAULT INJECTION"
OPPOSITE_OS = MappingProxyType({"macos": "windows", "windows": "macos"})  # read-only: no fault can change it


@dataclass(frozen=True)
class FaultOutcome:
    hits: list
    applied: bool
    detail: str


def _renumber(hits: list[dict], top_k: int) -> list[dict]:
    unique, seen = [], set()
    for hit in hits:
        if hit["doc_id"] not in seen:
            seen.add(hit["doc_id"])
            unique.append(hit)
    return [{**h, "rank": i} for i, h in enumerate(unique[:top_k], start=1)]


def _synthetic(doc_id: str) -> dict:
    return {"rank": 0, "doc_id": doc_id, "lexical_score": None, "matched_terms": [], "synthetic": True}


def _first_current_device_vpn(hits: list[dict], corpus: Corpus):
    docs = corpus.by_id()
    for index, hit in enumerate(hits):
        doc = docs.get(hit["doc_id"])
        if doc and doc.status == "approved" and doc.topic == "vpn" and doc.os in OPPOSITE_OS:
            return index, doc
    return None, None


def apply_retrieval_fault(name: str, hits: list[dict], corpus: Corpus, top_k: int) -> FaultOutcome:
    """Apply obsolete-first or wrong-os to retrieved hits (dictionaries)."""
    index, current = _first_current_device_vpn(hits, corpus)
    if current is None:
        return FaultOutcome(hits, False, "NOT APPLIED: no positively scored current device-specific VPN guide was retrieved.")
    if name == "obsolete-first":
        counterpart = current.supersedes
        if counterpart is None or corpus.get(counterpart) is None:
            return FaultOutcome(hits, False, f"NOT APPLIED: {current.doc_id} has no obsolete counterpart.")
        new_hits = _renumber([_synthetic(counterpart)] + hits, top_k)
        return FaultOutcome(new_hits, True, f"Injected {counterpart} (obsolete counterpart of {current.doc_id}) at rank 1.")
    if name == "wrong-os":
        opposite = OPPOSITE_OS[current.os]
        replacement = next((d for d in corpus.documents if d.status == "approved" and d.topic == "vpn" and d.os == opposite), None)
        if replacement is None:
            return FaultOutcome(hits, False, f"NOT APPLIED: there is no current {opposite} VPN guide to substitute.")
        replaced = list(hits)
        replaced[index] = _synthetic(replacement.doc_id)
        return FaultOutcome(_renumber(replaced, top_k), True,
                            f"Replaced {current.doc_id} with {replacement.doc_id} (the {opposite} guide) at rank {index + 1}.")
    raise ValueError(f"{name!r} is not a retrieval fault")


def apply_drop_required(hits: list[dict], expected_ids: list[str], top_k: int) -> FaultOutcome:
    """Remove the first expected document (in expected order) that was retrieved. Harness only."""
    if not expected_ids:
        return FaultOutcome(hits, False, "NOT APPLIED: the case has no expected documents to drop.")
    retrieved = [h["doc_id"] for h in hits]
    target = next((d for d in expected_ids if d in retrieved), None)
    if target is None:
        return FaultOutcome(hits, False, "NOT APPLIED: no expected document was retrieved, so there is nothing to remove.")
    return FaultOutcome(_renumber([h for h in hits if h["doc_id"] != target], top_k), True,
                        f"Removed expected document {target} from the retrieved results.")


def apply_fault(name: str | None, hits: list[dict], corpus: Corpus, top_k: int, expected_ids: list[str]) -> FaultOutcome:
    if name is None:
        return FaultOutcome(hits, False, "No fault requested.")
    if name not in FAULTS:
        raise ValueError(f"Unknown fault {name!r}. Allowed: {', '.join(FAULTS)}")
    if name == "drop-required":
        return apply_drop_required(hits, expected_ids, top_k)
    return apply_retrieval_fault(name, hits, corpus, top_k)
