"""
Shared pytest fixtures for the Northstar Services API test suite.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


def pytest_addoption(parser):
    """Register Day 2's test-only fault-injection flag.

    This has to be registered here, in the top-level tests/conftest.py,
    rather than in tests/day2/conftest.py: pytest only recognizes a
    command-line option if it comes from a conftest.py it scans while
    resolving which paths to collect, and a bare `python -m pytest -v`
    run from the project root (relying on `testpaths = ["tests"]` in
    pyproject.toml) never has a reason to look inside tests/day2/ at
    that early point. Registering it here means --day2-fault is always
    recognized, no matter how pytest is invoked.

    The flag does nothing by itself. Each value is only read by one
    file's own local fixture (tests/day2/test_03_ownership.py for
    "ownership"; tests/day2/test_04_schema.py for "missing-status" and
    "wrong-status-type"), so it has zero effect on any other test file,
    and zero effect at all unless it is explicitly passed.
    """
    parser.addoption(
        "--day2-fault",
        action="store",
        default=None,
        choices=["ownership", "missing-status", "wrong-status-type"],
        help=(
            "TEST-ONLY fault injection for Day 2 lessons. "
            "--day2-fault=ownership (tests/day2/test_03_ownership.py) "
            "monkeypatches the BR02 ownership check to always pass. "
            "--day2-fault=missing-status / wrong-status-type "
            "(tests/day2/test_04_schema.py) monkeypatch BR04's VPN "
            "status response to drop or mistype its 'status' field. "
            "All three prove their respective tests would fail if the "
            "real behavior broke. Never affects any other test file, "
            "the real running application, or any persisted data."
        ),
    )


@pytest.fixture()
def client() -> TestClient:
    """A TestClient wired to the FastAPI app, with no network calls involved."""
    return TestClient(app)
