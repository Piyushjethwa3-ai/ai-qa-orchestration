"""
Process-wide services for the API routes that involve the agent (chat, tools, approvals, audit).

State is in memory only and starts empty when the process starts. It is built on first use, so importing
`app.main` (and every Day 1-2 test) is unchanged. Tests call `reset_services()` for a clean state.
"""

from __future__ import annotations

from itertools import count

from app.agent.stack import Stack
from app.governance.stack import build_governed_stack

_stack: Stack | None = None
_request_ids = count(1)


def get_services() -> Stack:
    global _stack
    if _stack is None:
        _stack = build_governed_stack()
    return _stack


def reset_services(**kwargs) -> Stack:
    """Replace the services with a fresh stack (optionally configured, e.g. a fixed clock) and return it."""
    global _stack
    _stack = build_governed_stack(**kwargs)
    return _stack


def next_request_id() -> str:
    return f"API-{next(_request_ids):05d}"
