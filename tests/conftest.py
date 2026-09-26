"""
Shared pytest fixtures for the Northstar Services API test suite.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient wired to the FastAPI app, with no network calls involved."""
    return TestClient(app)
