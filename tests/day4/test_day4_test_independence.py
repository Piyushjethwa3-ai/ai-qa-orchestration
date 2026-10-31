"""Guard: no test may import helpers from a module called "conftest".

Every conftest.py is loaded under that same name, so the import would mean whichever one pytest loaded
last, and a test could pass or fail depending on which test folders are run and in what order.
Shared helpers belong in a uniquely named module (for example tests/day4/day4_support.py).
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
PATTERN = re.compile(r"^\s*(from\s+conftest\s+import|import\s+conftest)\b", re.MULTILINE)


def test_no_test_imports_from_a_module_named_conftest():
    offenders = [str(p.relative_to(TESTS)) for p in TESTS.rglob("*.py") if p != Path(__file__).resolve() and PATTERN.search(p.read_text(encoding="utf-8"))]

    assert offenders == [], f"import shared helpers from a uniquely named module instead: {offenders}"


def test_the_guard_pattern_catches_the_original_mistake():
    assert PATTERN.search("    from conftest import sdk_response")
    assert PATTERN.search("import conftest")
    assert not PATTERN.search("from day4_support import sdk_response")
