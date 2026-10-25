"""Day 5: Markdown loading, manifest validation, safe paths and hashing."""

import json
import os

import pytest

from training_day5 import knowledge, paths
from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)


def problems_for(kb):
    problems, corpus = knowledge.inspect_corpus(kb)
    return problems, corpus


def test_real_knowledge_base_loads_eight_documents_with_content_read_from_markdown(corpus):
    assert len(corpus.documents) == 8
    assert sum(d.status == "approved" for d in corpus.documents) == 6 and sum(d.status == "obsolete" for d in corpus.documents) == 2
    for doc in corpus.documents:
        assert doc.content == (paths.KB_DIR / doc.path).read_text(encoding="utf-8")  # read directly from the file
        assert "synthetic training material" in doc.content.lower()


def test_manifest_holds_metadata_only_not_document_content():
    manifest = json.loads(paths.MANIFEST_PATH.read_text())

    assert {k for entry in manifest["documents"] for k in entry} == set(knowledge.REQUIRED_FIELDS)
    for entry in manifest["documents"]:
        assert "Never share passwords" not in json.dumps(entry)  # body text is not duplicated in JSON


def test_policy_file_is_not_indexed_as_support_knowledge(corpus, run_cli):
    policy = paths.POLICY_PATH.read_text()

    assert "day5_retrieval_policy" not in " ".join(d.path for d in corpus.documents)
    assert all(policy[:200] not in d.content for d in corpus.documents)
    assert paths.KB_DIR.resolve() not in paths.POLICY_PATH.resolve().parents
    assert run_cli("validate")[0] == 0


def test_validate_reports_a_policy_inside_the_knowledge_folder(run_cli, monkeypatch):
    monkeypatch.setattr(paths, "POLICY_PATH", paths.KB_DIR / "manifest.json")

    code, out, _ = run_cli("validate")

    assert code == 2 and "never indexed" in out


def test_hashes_change_when_content_or_manifest_changes(kb_copy, edit_manifest):
    _, base = problems_for(kb_copy)

    (kb_copy / "account-reset.md").write_text((kb_copy / "account-reset.md").read_text() + "\nExtra line.\n")
    _, content_changed = problems_for(kb_copy)
    assert content_changed.manifest_sha256 == base.manifest_sha256
    assert content_changed.knowledge_base_sha256 != base.knowledge_base_sha256
    assert content_changed.by_id()["KB-ACCOUNT-RESET"].content_sha256 != base.by_id()["KB-ACCOUNT-RESET"].content_sha256

    edit_manifest(lambda docs: docs[4].update(version=2))
    _, manifest_changed = problems_for(kb_copy)
    assert manifest_changed.manifest_sha256 != base.manifest_sha256
    assert manifest_changed.knowledge_base_sha256 != content_changed.knowledge_base_sha256


def test_identical_files_give_identical_hashes(corpus):
    assert knowledge.load_corpus().knowledge_base_sha256 == corpus.knowledge_base_sha256


def entry(docs, doc_id):
    return next(d for d in docs if d["doc_id"] == doc_id)


@pytest.mark.parametrize(
    "mutation, expected_text",
    [
        pytest.param(lambda d: d.append(dict(d[0])), "more than once", id="duplicate_doc_id"),
        pytest.param(lambda d: d[0].pop("topic"), "missing field", id="missing_field"),
        pytest.param(lambda d: d[0].update(os="linux"), "os must be one of", id="bad_os"),
        pytest.param(lambda d: d[0].update(status="draft"), "status must be one of", id="bad_status"),
        pytest.param(lambda d: d[0].update(version=0), "version must be", id="version_zero"),
        pytest.param(lambda d: d[0].update(version=True), "version must be", id="version_bool"),
        pytest.param(lambda d: d[0].update(version="2"), "version must be", id="version_string"),
        pytest.param(lambda d: d[0].update(doc_id="vpn mac"), "doc_id must look like", id="bad_id_shape"),
        pytest.param(lambda d: d[0].update(title="  "), "title must be non-empty", id="blank_title"),
        pytest.param(lambda d: d[0].update(path="no-such-file.md"), "does not exist", id="missing_file"),
        pytest.param(lambda d: d[0].update(path="../escape.md"), "inside the knowledge folder", id="dotdot_path"),
        pytest.param(lambda d: d[0].update(path="/etc/hosts"), "inside the knowledge folder", id="absolute_path"),
        pytest.param(lambda d: d[0].update(path=d[1]["path"]), "used by another document", id="shared_path"),
        pytest.param(lambda d: d[0].update(path="manifest.json"), "must be Markdown", id="not_markdown"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(supersedes="KB-NOPE"), "unknown document", id="unknown_replacement"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(supersedes="KB-VPN-MAC-CURRENT"), "supersede itself", id="self_replacement"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(supersedes="KB-ACCOUNT-RESET"), "not marked obsolete", id="replaces_an_approved_doc"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(supersedes="KB-VPN-WIN-OLD"), "different os", id="replaces_other_os"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(version=1), "older version", id="not_newer"),
        pytest.param(lambda d: entry(d, "KB-VPN-WIN-CURRENT").update(supersedes="KB-VPN-MAC-OLD"), "different os", id="cross_os_replacement"),
        pytest.param(lambda d: entry(d, "KB-VPN-MAC-CURRENT").update(supersedes=None), "must be superseded", id="obsolete_without_replacement"),
    ],
)
def test_invalid_manifests_are_reported(edit_manifest, mutation, expected_text):
    kb = edit_manifest(mutation)

    problems, corpus = problems_for(kb)

    assert corpus is None
    assert any(expected_text in p for p in problems), problems


def test_empty_synthetic_and_heading_problems_in_the_markdown_are_reported(kb_copy):
    (kb_copy / "account-reset.md").write_text("   \n")
    (kb_copy / "software-access.md").write_text("# Software access requests\n\nNo notice here.\n")
    (kb_copy / "vpn-outage.md").write_text((kb_copy / "vpn-outage.md").read_text().replace("# Suspected VPN outage process", "# A different heading"))
    (kb_copy / "vpn-mac-obsolete.md").write_text((kb_copy / "vpn-mac-obsolete.md").read_text().replace("KB-VPN-MAC-CURRENT", "the new guide"))

    problems, corpus = problems_for(kb_copy)
    text = "\n".join(problems)

    assert corpus is None
    assert "KB-ACCOUNT-RESET: file 'account-reset.md' is empty" in text
    assert "KB-SOFTWARE-ACCESS: the document must say it is synthetic training material" in text
    assert "KB-VPN-OUTAGE: the first Markdown heading must match the manifest title" in text
    assert "KB-VPN-MAC-OLD: the document must state that KB-VPN-MAC-CURRENT replaces it" in text


def test_a_symlink_that_leaves_the_knowledge_folder_is_refused(kb_copy, edit_manifest, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n\nSynthetic training material.\n")
    os.symlink(outside, kb_copy / "linked.md")
    kb = edit_manifest(lambda d: d[0].update(path="linked.md"))

    problems, _ = problems_for(kb)

    assert any("resolves outside the knowledge folder" in p for p in problems)


def test_resolve_doc_path_accepts_only_paths_inside_the_folder(kb_copy):
    assert knowledge.resolve_doc_path(kb_copy, "account-reset.md") == (kb_copy / "account-reset.md").resolve()
    for bad in ("../x.md", "/abs/x.md", "a/../../x.md", "", "  "):
        with pytest.raises(knowledge.KnowledgeError):
            knowledge.resolve_doc_path(kb_copy, bad)


def test_every_problem_is_listed_not_just_the_first(edit_manifest):
    kb = edit_manifest(lambda d: (d[0].update(os="linux"), d[1].update(status="draft"), d[2].update(version=0)))

    problems, _ = problems_for(kb)

    assert len(problems) >= 3
