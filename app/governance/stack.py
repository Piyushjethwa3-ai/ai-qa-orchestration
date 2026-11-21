"""Builds a complete GOVERNED agent stack: the Week 5 agent, but every tool call goes through the gateway."""

from __future__ import annotations

import time

from app.agent.confirmations import ConfirmationStore
from app.agent.runner import AgentRunner
from app.agent.sessions import SessionStore
from app.agent.stack import Stack
from app.agent.tools import ToolBackend
from app.governance import privileged
from app.governance.approvals import ApprovalService
from app.governance.audit import AuditLog
from app.governance.gateway import Gateway
from app.governance.planner import GovernedPlanner


def build_governed_stack(*, status_fixtures=None, tickets=None, corpus=None, max_steps: int = 6, max_retries: int = 2,
                         privileged_flow: bool = True, faults: dict | None = None, planner=None, audit_path=None,
                         approvers: dict | None = None, clock=time.time, ttl_seconds: int = 900,
                         audit_clock=None) -> Stack:
    confirmations = ConfirmationStore()
    backend = ToolBackend(status_fixtures=status_fixtures, tickets=tickets, corpus=corpus, confirmations=confirmations)
    approvals = ApprovalService(approvers=approvers, clock=clock, ttl_seconds=ttl_seconds)
    executions = privileged.install(backend, approvals)
    for tool, outcomes in (faults or {}).items():
        backend.script_faults(tool, outcomes)
    audit = AuditLog(audit_path, **({"clock": audit_clock} if audit_clock else {}))
    gateway = Gateway(backend, approvals, audit)
    sessions = SessionStore()
    runner = AgentRunner(gateway, sessions, confirmations, planner if planner is not None else GovernedPlanner(),
                         max_steps=max_steps, max_retries=max_retries, privileged=privileged_flow)
    return Stack(backend, sessions, confirmations, runner, gateway,
                 {"approvals": approvals, "audit": audit, "gateway": gateway, "executions": executions})
