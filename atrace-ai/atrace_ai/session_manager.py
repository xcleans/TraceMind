"""Session management for AI chat — framework-agnostic.

Manages per-trace chat sessions with cursor_session_id for --resume.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatSession:
    session_id: str
    trace_path: str
    cursor_session_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_ts: float = 0.0
    last_ts: float = 0.0


class SessionManager:
    """Thread-safe in-memory session store.

    Responsibilities:
      - Create / retrieve sessions per trace_path
      - Map trace_path → list[session_id] for history lookup
      - Append messages with role/source/timestamp
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._trace_sessions: dict[str, list[str]] = {}

    def get_or_create(
        self,
        trace_path: str,
        session_id: str | None = None,
    ) -> ChatSession:
        if session_id and session_id in self._sessions:
            s = self._sessions[session_id]
            s.last_ts = time.time()
            return s
        if not session_id:
            existing = self._trace_sessions.get(trace_path, [])
            if existing:
                s = self._sessions[existing[-1]]
                s.last_ts = time.time()
                return s
        return self._create(trace_path, session_id)

    def new_session(self, trace_path: str) -> ChatSession:
        return self._create(trace_path)

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def append_message(
        self,
        session: ChatSession,
        role: str,
        text: str,
        source: str = "",
    ) -> None:
        session.messages.append({
            "role": role,
            "text": text,
            "source": source,
            "ts": time.time(),
        })
        session.last_ts = time.time()

    def list_all(self) -> list[dict[str, Any]]:
        items = []
        for s in self._sessions.values():
            items.append({
                "session_id": s.session_id,
                "trace_path": s.trace_path,
                "message_count": len(s.messages),
                "created_ts": s.created_ts,
                "last_ts": s.last_ts,
                "has_cursor_session": bool(s.cursor_session_id),
            })
        items.sort(key=lambda x: -x["last_ts"])
        return items

    def sessions_for_trace(self, trace_path: str) -> list[dict[str, Any]]:
        sids = self._trace_sessions.get(trace_path, [])
        items = []
        for sid in sids:
            s = self._sessions.get(sid)
            if s:
                items.append({
                    "session_id": s.session_id,
                    "message_count": len(s.messages),
                    "created_ts": s.created_ts,
                    "last_ts": s.last_ts,
                    "has_cursor_session": bool(s.cursor_session_id),
                })
        items.sort(key=lambda x: -x["last_ts"])
        return items

    def _create(self, trace_path: str, session_id: str | None = None) -> ChatSession:
        sid = session_id or str(uuid.uuid4())
        now = time.time()
        s = ChatSession(
            session_id=sid,
            trace_path=trace_path,
            created_ts=now,
            last_ts=now,
        )
        self._sessions[sid] = s
        self._trace_sessions.setdefault(trace_path, []).append(sid)
        return s
