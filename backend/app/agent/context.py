"""Lightweight per-session conversation state (in memory, no personal data)."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

from app.agent.schemas import ParsedQuestion

MAX_SESSIONS = 500
TTL_S = 6 * 3600


@dataclass
class SessionState:
    last_parsed: ParsedQuestion | None = None
    focus_entity: str | None = None  # e.g. top region of the last result
    focus_dimension: str | None = None
    summary: str = ""
    turns: int = 0
    updated: float = field(default_factory=time.time)


class ContextStore:
    def __init__(self) -> None:
        self._data: OrderedDict[str, SessionState] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id: str) -> SessionState:
        with self._lock:
            now = time.time()
            for sid in [s for s, v in self._data.items() if now - v.updated > TTL_S]:
                del self._data[sid]
            state = self._data.pop(session_id, None) or SessionState()
            self._data[session_id] = state
            while len(self._data) > MAX_SESSIONS:
                self._data.popitem(last=False)
            return state

    def update(self, session_id: str, parsed: ParsedQuestion, focus_entity: str | None,
               focus_dimension: str | None, summary: str) -> None:
        state = self.get(session_id)
        state.last_parsed = parsed
        if focus_entity:
            state.focus_entity, state.focus_dimension = focus_entity, focus_dimension
        state.summary = summary[:300]
        state.turns += 1
        state.updated = time.time()


store = ContextStore()
