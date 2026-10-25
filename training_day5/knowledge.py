"""
Loading and validating the Day 5 knowledge base.

Authoritative metadata lives in knowledge/day5/manifest.json (doc_id, path,
title, topic, os, version, status, supersedes). Document CONTENT lives only in
the Markdown files and is read directly from them; it is never copied into JSON.
Each Markdown file is one document. There is no chunking.

inspect_corpus() collects every problem it can find instead of stopping at the
first, so one run shows everything to fix. load_corpus() raises if there is any.

These checks cover shape and consistency only. They cannot tell you whether the
guidance in a document is good.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from training_day5 import paths

ALLOWED_OS = ("macos", "windows", "any")
ALLOWED_STATUS = ("approved", "obsolete")
REQUIRED_FIELDS = ("doc_id", "path", "title", "topic", "os", "version", "status", "supersedes")
DOC_ID_PATTERN = re.compile(r"^KB-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
SYNTHETIC_NOTICE = "synthetic training material"


class KnowledgeError(ValueError):
    """The knowledge base is invalid. `problems` lists everything that was found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Document:
    doc_id: str
    path: str
    title: str
    topic: str
    os: str
    version: int
    status: str
    supersedes: str | None
    content: str
    content_sha256: str


@dataclass(frozen=True)
class Corpus:
    documents: tuple
    manifest_sha256: str
    knowledge_base_sha256: str

    def by_id(self) -> dict[str, Document]:
        return {doc.doc_id: doc for doc in self.documents}

    def get(self, doc_id: str) -> Document | None:
        return self.by_id().get(doc_id)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_doc_path(kb_dir: Path, relative: str) -> Path:
    """Resolve a manifest path safely inside kb_dir, or raise KnowledgeError.

    Rejects absolute paths, '..' escapes and symlinks that lead outside the folder
    (the path is fully resolved before it is compared with the folder).
    """
    if not isinstance(relative, str) or not relative.strip():
        raise KnowledgeError(["path must be non-empty text"])
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise KnowledgeError([f"path {relative!r} must be relative and stay inside the knowledge folder"])
    root = Path(kb_dir).resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise KnowledgeError([f"path {relative!r} resolves outside the knowledge folder"]) from None
    return resolved


def _first_heading(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def inspect_corpus(kb_dir: Path | None = None, manifest_path: Path | None = None) -> tuple[list[str], Corpus | None]:
    """Return (problems, corpus). corpus is None unless there are no problems."""
    kb_dir = Path(kb_dir) if kb_dir is not None else Path(paths.KB_DIR)
    manifest_path = Path(manifest_path) if manifest_path is not None else kb_dir / "manifest.json"
    problems: list[str] = []
    if not manifest_path.exists():
        return [f"Missing manifest: {paths.display(manifest_path)}"], None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json is not valid JSON ({exc})"], None
    entries = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        return ["manifest.json must contain a non-empty 'documents' list"], None

    loaded: dict[str, Document] = {}
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"manifest entry {index + 1}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be an object")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            problems.append(f"{where}: missing field(s) {', '.join(missing)}")
            continue
        doc_id = entry["doc_id"]
        if not isinstance(doc_id, str) or not DOC_ID_PATTERN.match(doc_id):
            problems.append(f"{where}: doc_id must look like KB-SOMETHING-ELSE")
            continue
        if doc_id in loaded:
            problems.append(f"{doc_id}: doc_id appears more than once")
            continue
        metadata_ok = True
        for field in ("path", "title", "topic"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                problems.append(f"{doc_id}: {field} must be non-empty text")
                metadata_ok = False
        if entry["os"] not in ALLOWED_OS:
            problems.append(f"{doc_id}: os must be one of {ALLOWED_OS}, found {entry['os']!r}")
            metadata_ok = False
        if entry["status"] not in ALLOWED_STATUS:
            problems.append(f"{doc_id}: status must be one of {ALLOWED_STATUS}, found {entry['status']!r}")
            metadata_ok = False
        if type(entry["version"]) is not int or entry["version"] < 1:
            problems.append(f"{doc_id}: version must be a whole number >= 1")
            metadata_ok = False
        if entry["supersedes"] is not None and not isinstance(entry["supersedes"], str):
            problems.append(f"{doc_id}: supersedes must be a doc_id or null")
            metadata_ok = False
        if not metadata_ok:
            continue  # without valid metadata the document cannot take part in the cross-checks
        if entry["path"] in seen_paths:
            problems.append(f"{doc_id}: path {entry['path']!r} is used by another document")
        seen_paths.add(entry["path"])
        try:
            file_path = resolve_doc_path(kb_dir, entry["path"])
        except KnowledgeError as exc:
            problems.append(f"{doc_id}: {exc.problems[0]}")
            continue
        if file_path.suffix.lower() != ".md":
            problems.append(f"{doc_id}: document files must be Markdown (.md)")
            continue
        if not file_path.is_file():
            problems.append(f"{doc_id}: file {entry['path']!r} does not exist")
            continue
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            problems.append(f"{doc_id}: file {entry['path']!r} is empty")
            continue
        if SYNTHETIC_NOTICE not in content.lower():
            problems.append(f"{doc_id}: the document must say it is synthetic training material")
        if _first_heading(content) != entry["title"]:
            problems.append(f"{doc_id}: the first Markdown heading must match the manifest title")
        loaded[doc_id] = Document(doc_id, entry["path"], entry["title"], entry["topic"], entry["os"], entry["version"],
                                  entry["status"], entry["supersedes"], content, sha256_text(content))

    # Replacement references.
    replaced_by: dict[str, list[str]] = {}
    for doc in loaded.values():
        if doc.supersedes is None:
            continue
        target = loaded.get(doc.supersedes)
        if doc.supersedes == doc.doc_id:
            problems.append(f"{doc.doc_id}: a document cannot supersede itself")
        elif target is None:
            problems.append(f"{doc.doc_id}: supersedes unknown document {doc.supersedes}")
        else:
            replaced_by.setdefault(target.doc_id, []).append(doc.doc_id)
            if target.status != "obsolete":
                problems.append(f"{doc.doc_id}: supersedes {target.doc_id}, which is not marked obsolete")
            if target.os != doc.os:
                problems.append(f"{doc.doc_id}: supersedes {target.doc_id}, which is for a different os")
            if target.version >= doc.version:
                problems.append(f"{doc.doc_id}: supersedes {target.doc_id}, which does not have an older version")
            if doc.status != "approved":
                problems.append(f"{doc.doc_id}: only an approved document can supersede another")
    for doc in loaded.values():
        replacements = replaced_by.get(doc.doc_id, [])
        if len(replacements) > 1:
            problems.append(f"{doc.doc_id}: superseded by more than one document ({', '.join(sorted(replacements))})")
        if doc.status == "obsolete":
            if not replacements:
                problems.append(f"{doc.doc_id}: an obsolete document must be superseded by an approved document")
            elif replacements[0] not in doc.content:
                problems.append(f"{doc.doc_id}: the document must state that {replacements[0]} replaces it")

    if problems:
        return problems, None
    documents = tuple(sorted(loaded.values(), key=lambda d: d.doc_id))
    manifest_sha = sha256_file(manifest_path)
    kb_sha = sha256_text(manifest_sha + "\n" + "\n".join(f"{d.doc_id}:{d.content_sha256}" for d in documents))
    return [], Corpus(documents, manifest_sha, kb_sha)


def load_corpus(kb_dir: Path | None = None, manifest_path: Path | None = None) -> Corpus:
    problems, corpus = inspect_corpus(kb_dir, manifest_path)
    if problems:
        raise KnowledgeError(problems)
    return corpus
