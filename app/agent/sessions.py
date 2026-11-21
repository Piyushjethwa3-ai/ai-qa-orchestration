"""
Per-employee, per-session conversation state (BR10).

State is keyed by (employee_id, session_id). Two employees using the same session_id string get two
separate states, and one employee's two sessions are separate too. Nothing is shared or reused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_HISTORY = 20


@dataclass
class SessionState:
    employee_id: str
    session_id: str
    slots: dict = field(default_factory=dict)     # os, topic, issue, last_ticket_id ...
    pending: dict | None = None                    # a proposed action waiting for the employee's yes
    history: list = field(default_factory=list)    # REDACTED text only


class SessionStore:
    def __init__(self):
        self._sessions: dict[tuple, SessionState] = {}

    def get(self, employee_id: str, session_id: str) -> SessionState:
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise ValueError("session_id must be 1-64 characters: letters, digits, '.', '_' or '-'")
        key = (employee_id, session_id)
        if key not in self._sessions:
            self._sessions[key] = SessionState(employee_id, session_id)
        return self._sessions[key]

    def peek(self, employee_id: str, session_id: str):
        return self._sessions.get((employee_id, session_id))

    def __len__(self) -> int:
        return len(self._sessions)

    @staticmethod
    def remember(state: SessionState, role: str, text: str) -> None:
        state.history.append({"role": role, "text": text})
        del state.history[:-MAX_HISTORY]
