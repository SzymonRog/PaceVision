"""
SessionManager — registry of active ``LiveSession`` instances.

Enforces the maximum session limit and provides CRUD operations
used by the REST API endpoints.
"""

from __future__ import annotations

import asyncio

from core.config import settings
from core.exceptions import SessionLimitReached, SessionNotFound
from schemas.session import SessionInfo
from session.live_session import LiveSession


class SessionManager:
    """Singleton-style manager attached to the FastAPI app state."""

    def __init__(self, max_sessions: int | None = None) -> None:
        self._max = max_sessions or settings.max_sessions
        self._sessions: dict[str, LiveSession] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_session(
        self,
        device_index: int = 0,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> LiveSession:
        """Create and start a new live session.

        Raises ``SessionLimitReached`` if the cap has been hit.
        """
        if len(self._sessions) >= self._max:
            raise SessionLimitReached(
                f"Maximum of {self._max} concurrent sessions reached."
            )

        session = LiveSession(device_index=device_index, loop=loop)
        session.start()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> LiveSession:
        """Return a session by ID, or raise ``SessionNotFound``."""
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(f"Session '{session_id}' not found.")
        return session

    def list_sessions(self) -> list[SessionInfo]:
        """Return info for all active sessions."""
        return [
            SessionInfo(
                session_id=s.session_id,
                status=s.status,
                created_at=s.created_at,
                frame_count=s.frame_count,
                fps=s.fps,
            )
            for s in self._sessions.values()
        ]

    def stop_session(self, session_id: str) -> None:
        """Stop and remove a session."""
        session = self.get_session(session_id)
        session.stop()
        del self._sessions[session_id]

    def shutdown_all(self) -> None:
        """Stop all sessions. Called during application shutdown."""
        for session in list(self._sessions.values()):
            session.stop()
        self._sessions.clear()
