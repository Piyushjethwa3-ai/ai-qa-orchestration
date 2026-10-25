"""Day 5: filtering, scoring, deterministic ordering and input checks."""

import inspect

import pytest

from training_day5 import cli, evaluate, knowledge, retriever
from training_day5.retriever import RetrievalError, normalise_os, retrieve, tokenise
from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)

ALIAS_CASES = [("mac", "macos"), ("macOS", "macos"), ("Mac OS", "macos"), ("  MACOS  ", "macos"), ("macintosh", "macos"),
               ("windows", "windows"), ("Windows 11", "windows"), ("WIN", "windows"),
               ("any", "any"), ("ALL", "any"), ("", "any"), (None, "any"), ("linux", "linux"), ("  Linux ", "linux")]


@pytest.mark.parametrize("raw, expected", ALIAS_CASES)
def test_os_aliases_are_normalised_consistently(raw, expected):
    assert normalise_os(raw) == expected


def ids(result):
    return [h.doc_id for h in result.hits]


def test_the_retriever_cannot_see_labels():
    parameters = list(inspect.signature(retrieve).parameters)

    assert parameters == ["query", "os", "top_k", "corpus", "allowed_statuses"]
    assert not any(word in " ".join(parameters) for word in ("case", "expected", "prohibited", "answerable", "label"))


def test_retrieve_case_passes_only_query_os_and_top_k(run_cli, monkeypatch):
    seen = {}
    real = retriever.retrieve

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(retriever, "retrieve", spy)
    run_cli("retrieve", "--case", "R07", "--top-k", "2")

    assert set(seen) == {"query", "os", "top_k", "corpus"}
    assert seen["os"] == "macos" and seen["top_k"] == 2 and "escalation" in seen["query"]


def test_evaluation_calls_the_retriever_with_only_query_os_and_top_k(corpus):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return retrieve(**kwargs)

    case = {"case_id": "T1", "query": "account password reset", "os": "any", "answerable": True,
            "expected_doc_ids": ["KB-ACCOUNT-RESET"], "prohibited_doc_ids": []}
    evaluate.run_evaluation([case], corpus, 3, retrieve_fn=fake)

    assert [set(c) for c in calls] == [{"query", "os", "top_k", "corpus"}]
    assert "KB-ACCOUNT-RESET" not in str(calls[0]["query"])


def test_only_approved_documents_are_ever_returned(corpus):
    for os_value in ("macos", "windows", "any", "linux"):
        result = retrieve("retired vpn client guidance obsolete historical current", os_value, 8, corpus)
        assert {corpus.by_id()[i].status for i in ids(result)} <= {"approved"}


def test_the_status_filter_is_what_keeps_obsolete_guides_out(corpus):
    normal = retrieve("retired Mac VPN client guidance", "macos", 8, corpus)
    diagnostic = retrieve("retired Mac VPN client guidance", "macos", 8, corpus, allowed_statuses=("approved", "obsolete"))

    assert "KB-VPN-MAC-OLD" not in ids(normal) and "KB-VPN-MAC-OLD" in ids(diagnostic)


def test_a_known_os_permits_matching_os_and_general_documents_only(corpus):
    mac = ids(retrieve("vpn password change guidance outage escalate account software", "macos", 8, corpus))
    win = ids(retrieve("vpn password change guidance outage escalate account software", "windows", 8, corpus))

    assert "KB-VPN-MAC-CURRENT" in mac and "KB-VPN-WIN-CURRENT" not in mac
    assert "KB-VPN-WIN-CURRENT" in win and "KB-VPN-MAC-CURRENT" not in win
    assert {"KB-VPN-OUTAGE", "KB-ACCOUNT-RESET"} <= set(mac) & set(win)  # os=any documents are available to both


@pytest.mark.parametrize("os_value", ["any", None, "", "linux", "plan9"])
def test_unknown_or_any_os_permits_general_documents_only(corpus, os_value):
    result = retrieve("vpn password change current guidance reset", os_value, 8, corpus)

    assert ids(result) and all(corpus.by_id()[i].os == "any" for i in ids(result))
    if os_value == "linux":
        assert "unrecognised OS" in result.os_note


def test_results_are_ranked_by_score_then_doc_id_and_are_deterministic(corpus):
    first = retrieve("vpn password change", "macos", 8, corpus)
    second = retrieve("vpn password change", "macos", 8, corpus)

    assert first == second
    pairs = [(-h.score, h.doc_id) for h in first.hits]
    assert pairs == sorted(pairs)
    assert [h.rank for h in first.hits] == list(range(1, len(first.hits) + 1))


def test_equal_scores_are_broken_by_doc_id(kb_copy, edit_manifest):
    for name in ("zzz-tie.md", "aaa-tie.md"):
        (kb_copy / name).write_text(f"# Tie breaker topic\n\nSynthetic training material. Quokka policy.\n")
    kb = edit_manifest(lambda d: d.extend(
        {"doc_id": f"KB-{n}-TIE", "path": f"{n.lower()}-tie.md", "title": "Tie breaker topic", "topic": "tie", "os": "any",
         "version": 1, "status": "approved", "supersedes": None} for n in ("ZZZ", "AAA")))
    tied = knowledge.load_corpus(kb)

    result = retrieve("quokka", "any", 5, tied)

    assert ids(result) == ["KB-AAA-TIE", "KB-ZZZ-TIE"] and result.hits[0].score == result.hits[1].score


def test_only_positive_scores_are_returned_and_results_are_unique(corpus):
    assert retrieve("zebra giraffe", "any", 5, corpus).hits == ()
    hits = ids(retrieve("vpn vpn vpn password password", "macos", 8, corpus))
    assert len(hits) == len(set(hits))


def test_top_k_limits_the_results(corpus):
    assert len(retrieve("vpn password change", "macos", 1, corpus).hits) == 1
    assert len(retrieve("vpn password change", "macos", 2, corpus).hits) == 2
    assert ids(retrieve("vpn password change", "macos", 1, corpus)) == ids(retrieve("vpn password change", "macos", 3, corpus))[:1]


@pytest.mark.parametrize("bad", [0, -1, True, 2.0, "3", None, 1.5])
def test_nonpositive_or_non_integer_top_k_is_rejected(corpus, bad):
    with pytest.raises(RetrievalError):
        retrieve("vpn", "any", bad, corpus)


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_a_blank_or_non_text_query_is_rejected(corpus, bad):
    with pytest.raises(RetrievalError):
        retrieve(bad, "any", 3, corpus)


def test_document_ids_are_never_scored(corpus):
    assert tokenise("see KB-VPN-MAC-CURRENT now") == ["see", "now"]
    assert retrieve("KB-VPN-MAC-CURRENT KB-VPN-OUTAGE", "macos", 5, corpus).hits == ()


def test_tokenising_uses_a_fixed_stopword_list_and_plural_stripping():
    assert tokenise("How do I reset my passwords for access?") == ["reset", "password", "access"]
    assert tokenise("Windows VPN") == ["window", "vpn"]
    assert "the" in retriever.STOPWORDS and "vpn" not in retriever.STOPWORDS


def test_score_is_title_weighted_lexical_overlap_not_a_probability(corpus):
    result = retrieve("escalation", "any", 3, corpus)
    hit = result.hits[0]

    assert hit.doc_id == "KB-SUPPORT-ESCALATION"
    assert hit.score == retriever.TITLE_WEIGHT + retriever.CONTENT_WEIGHT and isinstance(hit.score, int)
    assert hit.matched_terms == ("escalation",)


def test_cli_labels_scores_as_lexical_not_confidence(run_cli):
    code, out, _ = run_cli("retrieve", "--query", "vpn password change", "--os", "macos", "--top-k", "3")

    assert code == 0 and "lexical score" in out and "not confidence probabilities" in out


def test_cli_rejects_invalid_retrieve_inputs(run_cli):
    assert run_cli("retrieve", "--query", "vpn", "--top-k", "0")[0] == 2
    assert run_cli("retrieve", "--case", "R99")[0] == 2
    assert run_cli("retrieve", "--case", "R01", "--os", "macos")[0] == 2
    assert run_cli("retrieve")[0] == 2  # one of --case / --query is required
    assert run_cli("retrieve", "--query", "vpn", "--case", "R01")[0] == 2  # not both
