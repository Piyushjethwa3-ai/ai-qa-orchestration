"""Where the Day 5 inputs and reports live. Everything hangs off the repository root."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

KB_DIR = REPO_ROOT / "knowledge" / "day5"
MANIFEST_PATH = KB_DIR / "manifest.json"
CASES_PATH = REPO_ROOT / "datasets" / "day5" / "retrieval_cases.json"
# The retrieval policy documents the rules. It lives OUTSIDE the knowledge base and is never indexed.
POLICY_PATH = REPO_ROOT / "policies" / "day5_retrieval_policy.md"

# Tests point this at a temporary folder so they never write into reports/day5.
REPORTS_DIR = REPO_ROOT / "reports" / "day5"


def display(path) -> str:
    """Show a path relative to the repository root when possible."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
