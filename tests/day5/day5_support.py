"""
Shared fixtures for the Day 5 tests, imported explicitly by each test module.

This is deliberately NOT named conftest.py. Every conftest.py is loaded under the module name
"conftest", and the Day 4 tests import helpers with `from conftest import ...` while they run, so a
tests/day5/conftest.py (which sorts last) would shadow Day 4's and break those tests in a full run.
A uniquely named module cannot.

Every Day 5 test runs offline and isolated:

- Network connections raise an error, so nothing can reach the internet (Day 5 makes no
  model or network calls at all; this makes that a checked fact).
- Model/credential variables are removed for each test.
- Reports go to a temporary folder, never to reports/day5.
- Tests that change the knowledge base work on a COPY of knowledge/day5 in a temporary folder.

This is a separate copy of the Day 3/Day 4 protection on purpose: those guards are unchanged
and earlier suites are not affected. There is no new pytest flag.
"""

import json
import shutil
import socket

import pytest

from training_day5 import cli, knowledge, paths


@pytest.fixture(autouse=True)
def _offline_and_isolated(monkeypatch, tmp_path):
    for variable in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_JUDGE_MODEL", "DAY4_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    def _blocked(*args, **kwargs):
        raise RuntimeError("Network access is disabled in Day 5 tests.")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(paths, "REPORTS_DIR", tmp_path / "reports_day5")


@pytest.fixture()
def run_cli(capsys):
    """Run `python -m training_day5 ...` in-process. Returns (exit_code, stdout, stderr)."""

    def _run(*args):
        try:
            code = cli.main([str(a) for a in args])
        except SystemExit as exc:  # argparse rejects bad arguments this way
            code = exc.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture()
def corpus():
    return knowledge.load_corpus()


@pytest.fixture()
def kb_copy(tmp_path):
    """A writable copy of knowledge/day5. Tests edit the copy, never the real files."""
    target = tmp_path / "kb"
    shutil.copytree(paths.KB_DIR, target)
    return target


@pytest.fixture()
def edit_manifest(kb_copy):
    def _edit(mutate):
        path = kb_copy / "manifest.json"
        manifest = json.loads(path.read_text())
        mutate(manifest["documents"])
        path.write_text(json.dumps(manifest))
        return kb_copy

    return _edit


def hit(doc_id: str, rank: int, score: int = 5) -> dict:
    return {"rank": rank, "doc_id": doc_id, "lexical_score": score, "matched_terms": ["x"], "synthetic": False}


@pytest.fixture()
def make_hit():
    return hit


@pytest.fixture()
def reports_dir():
    """Load every saved results.json in the temporary reports folder, keyed by run ID."""

    def _load():
        out = {}
        if paths.REPORTS_DIR.exists():
            for folder in sorted(paths.REPORTS_DIR.iterdir()):
                out[folder.name] = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        return out

    return _load
