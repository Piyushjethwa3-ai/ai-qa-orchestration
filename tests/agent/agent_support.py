"""
Shared fixtures for the agent (Week 5) and Day 6 governance tests, imported explicitly by each test module.

Deliberately NOT named conftest.py (see tests/day5/day5_support.py for why: every conftest.py shares the
module name "conftest" and would shadow the Day 4 helpers). Every test here runs offline: sockets are
blocked, model variables are removed, and nothing is written outside a temporary folder.
"""

import json
import socket
from pathlib import Path

import pytest

from app import data

ROOT = Path(__file__).resolve().parents[2]
MAC = "My VPN stopped working after I changed my password on my Mac"
WIN = "My VPN stopped working after I changed my password on my Windows laptop"


@pytest.fixture(autouse=True)
def _offline_and_isolated(monkeypatch):
    for variable in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_JUDGE_MODEL", "DAY4_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    def _blocked(*args, **kwargs):
        raise RuntimeError("Network access is disabled in agent tests.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def data_files_snapshot() -> dict:
    return {p.name: p.read_bytes() for p in sorted(Path(data.DATA_DIR).glob("*.json"))}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
