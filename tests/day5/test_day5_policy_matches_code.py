"""Day 5: the retrieval policy and README describe what the code actually does.

The policy documents the rules and Python enforces them. These tests fail when the two drift apart, in
either direction: a rule changed in code but not in the policy, or a policy claim the code does not back up.
"""

import re
from pathlib import Path

from day5_support import (  # noqa: F401  (shared fixtures; the autouse one must be imported by every module)
    _offline_and_isolated, corpus, edit_manifest, kb_copy, make_hit, reports_dir, run_cli)
from training_day5 import faults, paths, retriever

POLICY = Path(paths.POLICY_PATH).read_text(encoding="utf-8")
README = (Path(paths.REPO_ROOT) / "README.md").read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_the_policys_stopword_block_is_exactly_the_codes_stopword_list():
    block = re.search(r"### Fixed stopword list.*?```text\n(.*?)```", POLICY, re.S).group(1).split()

    assert set(block) == set(retriever.STOPWORDS) and len(block) == len(set(block)) == len(retriever.STOPWORDS)
    assert f"These {len(retriever.STOPWORDS)} words" in POLICY  # the stated count is the real count
    assert block == sorted(block)


def test_the_policy_states_the_scoring_weights_the_code_uses():
    assert (retriever.CONTENT_WEIGHT, retriever.TITLE_WEIGHT) == (1, 2)
    assert "+1 if it appears in the document content" in POLICY and "+2 if it appears in the manifest title" in POLICY
    assert "not confidence probabilities" in POLICY and "positive" in POLICY.lower()


def test_the_policy_names_the_os_aliases_the_code_recognises():
    # (policy example, canonical value the policy says it becomes)
    for alias in ("mac", "macOS", "Mac OS", "macintosh"):
        assert f"`{alias}`" in POLICY and retriever.normalise_os(alias) == "macos"
    for alias in ("win", "Windows 11"):
        assert f"`{alias}`" in POLICY and retriever.normalise_os(alias) == "windows"
    for alias in ("any", "all", "general", "unknown"):
        assert f"`{alias}`" in POLICY and retriever.normalise_os(alias) == "any"
    assert retriever.normalise_os("") == "any" and retriever.normalise_os("Linux") == "linux"
    assert "stays as typed" in POLICY


def test_the_policy_lists_exactly_the_implemented_faults():
    table = section(POLICY, "## 5. Synthetic fault handling", "## 6.")
    named = set(re.findall(r"^\| `([a-z-]+)` \|", table, re.M))

    assert named == set(faults.FAULTS) and faults.SYNTHETIC_LABEL in POLICY and "NOT APPLIED" in POLICY


def test_the_policy_and_the_code_agree_that_ids_are_only_removed_in_canonical_upper_case():
    assert retriever.tokenise("see KB-VPN-MAC-CURRENT") == ["see"]  # upper-case ID removed, as the policy says
    # Documented limitation: a lower-case ID is not recognised and is scored as ordinary words. If ID removal is
    # ever made case-insensitive, update this test, the policy's Tokenising bullet and the README together.
    assert retriever.tokenise("see kb-vpn-mac-current") == ["see", "kb", "vpn", "mac", "current"]
    assert "upper-case form" in POLICY and "not** recognised as an ID" in POLICY
    assert "only when written in upper case" in README


def test_the_policy_states_each_of_the_intended_rules():
    lowered = POLICY.lower()
    for fragment in ("normal mode considers **approved** documents only", "permits documents for that os **and** documents with `os: any`",
                     "permits documents with `os: any` **only**", "eligibility is not relevance",
                     "one markdown file is one document", "no chunking", "python enforces these rules",
                     "it is **not** support knowledge", "never indexed"):
        assert fragment in lowered, fragment


def test_the_readme_lists_the_real_cli_commands_and_the_real_stopword_count():
    sec = section(README, "## Day 5:", "\n## Business rules")
    commands = re.findall(r"python -m training_day5 ([a-z-]+)", sec)

    assert {"validate", "list-docs", "show-doc", "show-case", "retrieve", "evaluate", "summary"} <= set(commands)
    assert f"a fixed list of {len(retriever.STOPWORDS)} common words" in sec
