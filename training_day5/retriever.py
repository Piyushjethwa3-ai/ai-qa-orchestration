"""
The Day 5 retriever: local, deterministic, lexical. Standard library only.

INPUTS. retrieve() receives a query, an OS value and top_k (plus the loaded
corpus). It never receives case IDs, expected IDs, prohibited IDs or whether a
question is answerable, so it cannot use them.

FILTERING (decided before scoring):
- Normal mode considers APPROVED documents only.
- A known OS (macos or windows) permits documents for that OS and os=any documents.
- An unknown OS (for example linux) or os=any permits os=any documents only.

SCORING. The query and each document are tokenised the same way: lower-case,
letters and digits only, document IDs like KB-VPN-MAC-CURRENT removed first (an
ID is never scored), a fixed stopword list dropped, and a trailing plural "s"
removed from words longer than three letters ("passwords" -> "password",
"access" is left alone). For each DISTINCT query term:

    +1 if the term appears in the document content (Markdown, headings included)
    +2 if the term appears in the manifest title

The score is the sum. It is a lexical overlap count. It is NOT a probability or
a confidence, and a positive score does not mean the document answers the
question. Only documents with a positive score are returned, best first, ties
broken by doc_id, up to top_k.

KNOWN LIMITS. There is no stemming beyond plural "s", no synonyms and no term
weighting by rarity. A general document that happens to share a word with an
unsupported question WILL be returned; that failure is kept, not hidden.
"""

import re
from dataclasses import dataclass

from training_day5.knowledge import Corpus, load_corpus

RETRIEVER_VERSION = "day5-lexical-v1"
TITLE_WEIGHT = 2
CONTENT_WEIGHT = 1

STOPWORDS = frozenset("""
a about after all an and any are as at be been but by can could did do does for from had has have how i if in into is it
its me my no not of on or our should so than that the their then there these they this to up was we were what when
where which who why will with would you your
""".split())

OS_ALIASES = {
    "macos": ("macos", "mac", "mac os", "macintosh", "osx", "os x"),
    "windows": ("windows", "win", "windows 10", "windows 11", "win10", "win11"),
    "any": ("any", "all", "general", "none", "unknown", ""),
}
KNOWN_DEVICE_OS = ("macos", "windows")
_DOC_ID = re.compile(r"\bKB-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")
_WORD = re.compile(r"[a-z0-9]+")


class RetrievalError(ValueError):
    """The retriever was given invalid input."""


@dataclass(frozen=True)
class Hit:
    rank: int
    doc_id: str
    score: int
    matched_terms: tuple

    def to_dict(self) -> dict:
        return {"rank": self.rank, "doc_id": self.doc_id, "lexical_score": self.score,
                "matched_terms": list(self.matched_terms), "synthetic": False}


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    os_input: str | None
    os_normalised: str
    os_note: str
    top_k: int
    hits: tuple
    candidate_count: int
    excluded_count: int
    query_terms: tuple


def normalise_os(value) -> str:
    """Map an OS value to macos, windows or any. An unrecognised value (for example linux) is kept as typed, lower-cased."""
    text = "" if value is None else " ".join(str(value).strip().lower().split())
    for canonical, aliases in OS_ALIASES.items():
        if text in aliases:
            return canonical
    return text


def tokenise(text: str) -> list[str]:
    """Lower-case words, document IDs removed, stopwords dropped, trailing plural 's' removed."""
    words = _WORD.findall(_DOC_ID.sub(" ", str(text)).lower())
    out = []
    for word in words:
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def validate_top_k(top_k) -> int:
    if type(top_k) is not int or top_k < 1:  # rejects True, 2.0 and "3"
        raise RetrievalError(f"top_k must be a whole number of at least 1, got {top_k!r}")
    return top_k


def eligible_documents(corpus: Corpus, os_normalised: str, allowed_statuses=("approved",)) -> list:
    known = os_normalised in KNOWN_DEVICE_OS
    return [d for d in corpus.documents
            if d.status in allowed_statuses and (d.os == "any" or (known and d.os == os_normalised))]


def retrieve(query: str, os: str | None, top_k: int, corpus: Corpus | None = None,
             allowed_statuses=("approved",)) -> RetrievalResult:
    """Return up to top_k unique documents with a positive lexical score. See the module docstring."""
    if not isinstance(query, str) or not query.strip():
        raise RetrievalError("query must be non-empty text")
    validate_top_k(top_k)
    corpus = corpus if corpus is not None else load_corpus()
    os_norm = normalise_os(os)
    note = ("recognised device OS" if os_norm in KNOWN_DEVICE_OS else
            "no OS filter: general (os=any) documents only" if os_norm == "any" else
            f"unrecognised OS {os_norm!r}: general (os=any) documents only")
    candidates = eligible_documents(corpus, os_norm, allowed_statuses)
    terms = sorted(set(tokenise(query)))
    scored = []
    for doc in candidates:
        title_tokens, content_tokens = set(tokenise(doc.title)), set(tokenise(doc.content))
        matched = [t for t in terms if t in title_tokens or t in content_tokens]
        score = sum((CONTENT_WEIGHT if t in content_tokens else 0) + (TITLE_WEIGHT if t in title_tokens else 0) for t in terms)
        if score > 0:
            scored.append((-score, doc.doc_id, tuple(matched)))
    scored.sort()  # best score first; ties by doc_id, so the order is always the same
    hits = tuple(Hit(rank, doc_id, -neg, matched) for rank, (neg, doc_id, matched) in enumerate(scored[:top_k], start=1))
    return RetrievalResult(query=query, os_input=os, os_normalised=os_norm, os_note=note, top_k=top_k, hits=hits,
                           candidate_count=len(candidates), excluded_count=len(corpus.documents) - len(candidates),
                           query_terms=tuple(terms))
