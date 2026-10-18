"""Where the Day 4 inputs and reports live. Everything hangs off the repository root."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DATASET_DIR = REPO_ROOT / "datasets" / "day4"
CASES_PATH = DATASET_DIR / "cases.json"
LABELS_PATH = DATASET_DIR / "human_labels.json"
RUBRIC_PATH = DATASET_DIR / "rubric.json"
REVIEWS_PATH = DATASET_DIR / "human_reviews.json"
REPLAY_PATH = DATASET_DIR / "replay_fixtures.json"

PROMPTS_DIR = REPO_ROOT / "prompts" / "day4"
JUDGE_PROMPT_PATH = PROMPTS_DIR / "judge.txt"
RESPONSE_PROMPT_PATHS = {"A": PROMPTS_DIR / "response_a.txt", "B": PROMPTS_DIR / "response_b.txt"}

JUDGE_SCHEMA_PATH = REPO_ROOT / "schemas" / "day4_judge_output.schema.json"

BUSINESS_RULES_PATH = REPO_ROOT / "docs" / "business_rules.md"

# Tests point this at a temporary folder so they never write into reports/day4.
REPORTS_DIR = REPO_ROOT / "reports" / "day4"


def display(path: Path) -> str:
    """Show a path relative to the repository root when possible."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
