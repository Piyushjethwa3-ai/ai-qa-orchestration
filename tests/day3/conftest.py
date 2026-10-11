"""
Day 3 test fixtures. Every Day 3 test runs offline:

- OPENAI_API_KEY and OPENAI_MODEL are removed for each test, so even a
  trainer's configured terminal can never trigger a paid call here.
- Opening a network connection raises an error, so an accidental live
  call fails loudly instead of quietly reaching the internet.
"""

import json
import socket

import pytest

from day3_lab import cli


@pytest.fixture(autouse=True)
def _offline_only(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    def _blocked(*args, **kwargs):
        raise RuntimeError("Network access is disabled in Day 3 tests.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture()
def run_cli(capsys):
    """Run `python -m day3_lab ...` in-process. Returns (exit_code, stdout, stderr)."""

    def _run(*args: str):
        try:
            code = cli.main([str(arg) for arg in args])
        except SystemExit as exc:  # argparse rejects bad arguments this way
            code = exc.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture()
def read_json():
    def _read(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    return _read
