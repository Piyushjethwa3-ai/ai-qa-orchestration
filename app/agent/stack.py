"""Builds one complete, isolated agent stack (backend, stores, runner). Used by tests, the evaluator and the API."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.confirmations import ConfirmationStore
from app.agent.runner import AgentRunner
from app.agent.sessions import SessionStore
from app.agent.tools import DirectInvoker, ToolBackend


@dataclass
class Stack:
    backend: ToolBackend
    sessions: SessionStore
    confirmations: ConfirmationStore
    runner: AgentRunner
    invoker: object = None
    extras: dict = None

    @property
    def gateway(self):
        """The governed tool gateway (Day 6), or None for a plain Week 5 stack."""
        return (self.extras or {}).get("gateway")


def build_stack(*, status_fixtures=None, tickets=None, corpus=None, max_steps: int = 6, max_retries: int = 2,
                privileged: bool = False, faults: dict | None = None, planner=None) -> Stack:
    confirmations = ConfirmationStore()
    backend = ToolBackend(status_fixtures=status_fixtures, tickets=tickets, corpus=corpus, confirmations=confirmations)
    for tool, outcomes in (faults or {}).items():
        backend.script_faults(tool, outcomes)
    sessions = SessionStore()
    invoker = DirectInvoker(backend)
    runner = AgentRunner(invoker, sessions, confirmations, planner, max_steps=max_steps, max_retries=max_retries,
                         privileged=privileged)
    return Stack(backend, sessions, confirmations, runner, invoker, {})
