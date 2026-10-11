"""
Where the Day 3 lab's input files live.

Every path is built from the repository root (the folder that contains
day3_lab/), so the lab finds its inputs no matter which folder the
terminal is in. Output folders passed with --out are different: they are
resolved from the terminal's current folder, like any other CLI path.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Supplied by the trainer pack and copied in unchanged.
SOURCE_CASES_PATH = REPO_ROOT / "day3_materials" / "day3_cases.json"
SOURCE_RUBRIC_PATH = REPO_ROOT / "day3_materials" / "day3_rubric.json"

# The copies the lab actually reads.
CASES_PATH = REPO_ROOT / "datasets" / "day3" / "cases.json"
RUBRIC_PATH = REPO_ROOT / "rubrics" / "day3" / "rubric.json"

# Written for this lab.
MOCK_RESPONSES_PATH = REPO_ROOT / "datasets" / "day3" / "mock_responses.json"
CLINIC_FIXTURES_PATH = REPO_ROOT / "datasets" / "day3" / "clinic_fixtures.json"
PROMPT_PATH = REPO_ROOT / "prompts" / "day3" / "response_v1.txt"
RESPONSE_SCHEMA_PATH = REPO_ROOT / "schemas" / "day3_response.schema.json"
CASES_SCHEMA_PATH = REPO_ROOT / "schemas" / "day3_cases.schema.json"
BUSINESS_RULES_PATH = REPO_ROOT / "docs" / "business_rules.md"


def display_path(path: Path) -> str:
    """Show a path relative to the repository root when possible."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)
