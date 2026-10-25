"""Day 5: each synthetic fault, detected with controlled fixtures; no leaking between commands."""


import pytest

from training_day5 import evaluate, faults, knowledge, retriever
from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)

MAC, WIN = "KB-VPN-MAC-CURRENT", "KB-VPN-WIN-CURRENT"


def ids(outcome):
    return [h["doc_id"] for h in outcome.hits]


# ------------------------------------------------------------------ obsolete-first

def test_obsolete_first_puts_the_obsolete_counterpart_at_rank_one_within_top_k(corpus, make_hit):
    hits = [make_hit(MAC, 1, 12), make_hit("KB-ACCOUNT-RESET", 2, 3), make_hit("KB-VPN-OUTAGE", 3, 3)]

    outcome = faults.apply_retrieval_fault("obsolete-first", hits, corpus, 3)

    assert outcome.applied and ids(outcome) == ["KB-VPN-MAC-OLD", MAC, "KB-ACCOUNT-RESET"]  # top-k 3 still respected
    assert [h["rank"] for h in outcome.hits] == [1, 2, 3]
    assert outcome.hits[0]["synthetic"] is True and outcome.hits[0]["lexical_score"] is None
    assert "KB-VPN-MAC-OLD" in outcome.detail


def test_obsolete_first_at_top_k_one_leaves_only_the_obsolete_guide(corpus, make_hit):
    outcome = faults.apply_retrieval_fault("obsolete-first", [make_hit(WIN, 1)], corpus, 1)

    assert outcome.applied and ids(outcome) == ["KB-VPN-WIN-OLD"]


@pytest.mark.parametrize("name", ["obsolete-first", "wrong-os"])
def test_vpn_faults_are_not_applied_without_a_current_device_specific_vpn_guide(corpus, make_hit, name):
    for hits in ([], [make_hit("KB-ACCOUNT-RESET", 1)], [make_hit("KB-VPN-OUTAGE", 1), make_hit("KB-SUPPORT-ESCALATION", 2)]):
        outcome = faults.apply_retrieval_fault(name, hits, corpus, 3)

        assert outcome.applied is False and outcome.hits == hits and outcome.detail.startswith("NOT APPLIED")


# ------------------------------------------------------------------ wrong-os

def test_wrong_os_swaps_in_the_opposite_current_guide_at_the_same_rank(corpus, make_hit):
    hits = [make_hit("KB-VPN-OUTAGE", 1), make_hit(MAC, 2), make_hit("KB-ACCOUNT-RESET", 3)]

    outcome = faults.apply_retrieval_fault("wrong-os", hits, corpus, 3)

    assert outcome.applied and ids(outcome) == ["KB-VPN-OUTAGE", WIN, "KB-ACCOUNT-RESET"]
    assert outcome.hits[1]["synthetic"] is True
    reverse = faults.apply_retrieval_fault("wrong-os", [make_hit(WIN, 1)], corpus, 3)
    assert ids(reverse) == [MAC]


def test_wrong_os_does_not_return_the_same_document_twice(corpus, make_hit):
    outcome = faults.apply_retrieval_fault("wrong-os", [make_hit(MAC, 1), make_hit(WIN, 2)], corpus, 3)

    assert ids(outcome) == [WIN] and [h["rank"] for h in outcome.hits] == [1]


# ------------------------------------------------------------------ drop-required (harness, uses labels)

def test_drop_required_removes_the_first_expected_document_in_expected_order(make_hit):
    hits = [make_hit(MAC, 1), make_hit("KB-SUPPORT-ESCALATION", 2), make_hit("KB-VPN-OUTAGE", 3)]

    outcome = faults.apply_drop_required(hits, ["KB-SUPPORT-ESCALATION", MAC], 3)

    assert outcome.applied and ids(outcome) == [MAC, "KB-VPN-OUTAGE"]  # expected order decides, not rank
    assert [h["rank"] for h in outcome.hits] == [1, 2]
    again = faults.apply_drop_required(hits, ["KB-SUPPORT-ESCALATION", MAC], 3)
    assert ids(again) == ids(outcome)  # stable


def test_drop_required_is_not_applied_without_expected_documents_or_matches(make_hit):
    assert faults.apply_drop_required([make_hit("KB-VPN-OUTAGE", 1)], [], 3).applied is False
    outcome = faults.apply_drop_required([make_hit("KB-VPN-OUTAGE", 1)], [MAC], 3)
    assert outcome.applied is False and "nothing to remove" in outcome.detail


def test_the_retriever_code_does_not_import_or_use_faults_or_labels():
    import ast

    tree = ast.parse(open(retriever.__file__, encoding="utf-8").read())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}

    assert not any(m and any(w in m for w in ("fault", "metrics", "cases", "evaluate")) for m in imported)
    assert not any(any(w in name.lower() for w in ("fault", "expected", "prohibited", "answerable", "label")) for name in names)


# ------------------------------------------------------------------ end to end through the harness

def case(case_id, query, os_value, expected, prohibited=("KB-VPN-MAC-OLD", "KB-VPN-WIN-OLD"), answerable=None):
    return {"case_id": case_id, "query": query, "os": os_value, "answerable": bool(expected) if answerable is None else answerable,
            "expected_doc_ids": list(expected), "prohibited_doc_ids": list(prohibited)}


MAC_CASE = case("T-MAC", "vpn password change on my mac", "macos", [MAC], ["KB-VPN-MAC-OLD", "KB-VPN-WIN-OLD", WIN])


def test_each_fault_is_detected_by_the_evaluation(corpus):
    normal = evaluate.run_evaluation([MAC_CASE], corpus, 3)["results"][0]
    assert normal["result"] == "PASS" and normal["fault"]["status"] == "NONE"

    obsolete = evaluate.run_evaluation([MAC_CASE], corpus, 3, "obsolete-first")["results"][0]
    assert obsolete["result"] == "FAIL" and obsolete["prohibited_matches"] == ["KB-VPN-MAC-OLD"] and obsolete["retrieved_ids"][0] == "KB-VPN-MAC-OLD"
    assert obsolete["recall"] == 1.0  # the right guide is still there; the fault is the prohibited document

    wrong = evaluate.run_evaluation([MAC_CASE], corpus, 3, "wrong-os")["results"][0]
    assert wrong["result"] == "FAIL" and wrong["missing_ids"] == [MAC] and wrong["prohibited_matches"] == [WIN] and wrong["recall"] == 0.0

    dropped = evaluate.run_evaluation([MAC_CASE], corpus, 3, "drop-required")["results"][0]
    assert dropped["result"] == "FAIL" and dropped["missing_ids"] == [MAC] and dropped["recall"] == 0.0 and dropped["prohibited_matches"] == []


def test_fault_status_is_recorded_per_case_and_for_the_run(corpus):
    general = case("T-ACC", "account password reset", "any", ["KB-ACCOUNT-RESET"])

    none_applied = evaluate.run_evaluation([general], corpus, 3, "obsolete-first")
    some_applied = evaluate.run_evaluation([MAC_CASE, general], corpus, 3, "obsolete-first")
    all_applied = evaluate.run_evaluation([MAC_CASE], corpus, 3, "obsolete-first")

    assert none_applied["fault"]["status"] == "NOT APPLIED" and "no fault demonstration can be claimed" in none_applied["fault"]["note"]
    assert none_applied["results"][0]["result"] == "PASS"  # an un-applied fault changes nothing
    assert some_applied["fault"]["status"] == "PARTIALLY APPLIED"
    assert some_applied["fault"]["applied_cases"] == ["T-MAC"] and some_applied["fault"]["not_applied_cases"] == ["T-ACC"]
    assert all_applied["fault"]["status"] == "APPLIED" and all_applied["fault"]["label"] == faults.SYNTHETIC_LABEL


def test_unknown_fault_is_rejected(corpus):
    with pytest.raises(ValueError):
        evaluate.run_evaluation([MAC_CASE], corpus, 3, "make-it-worse")


# ------------------------------------------------------------------ nothing leaks

def test_a_fault_does_not_leak_into_later_runs_or_change_stored_documents(corpus):
    before = knowledge.load_corpus().knowledge_base_sha256
    clean_first = evaluate.run_evaluation([MAC_CASE], corpus, 3)
    for name in faults.FAULTS:
        assert evaluate.run_evaluation([MAC_CASE], corpus, 3, name)["fault"]["mode"] == name
    clean_after = evaluate.run_evaluation([MAC_CASE], corpus, 3)

    assert clean_after == clean_first and clean_after["fault"]["mode"] == "none" and clean_after["fault"]["label"] is None
    assert knowledge.load_corpus().knowledge_base_sha256 == before == corpus.knowledge_base_sha256


def test_the_faults_module_keeps_no_mutable_state():
    state = [n for n, v in vars(faults).items() if not n.startswith("_") and isinstance(v, (list, dict, set))]

    assert state == []  # constants are tuples/strings; nothing a fault could leave behind


def test_a_fault_chosen_on_one_cli_command_does_not_carry_to_the_next(run_cli, reports_dir):
    run_cli("evaluate", "--cases", "R01", "--fault", "wrong-os")
    run_cli("evaluate", "--cases", "R01")

    runs = sorted(reports_dir().values(), key=lambda r: r["created_at"])
    assert [r["fault"]["mode"] for r in runs] == ["wrong-os", "none"]
    assert runs[1]["label"] is None and runs[1]["results"][0]["fault"]["status"] == "NONE"
