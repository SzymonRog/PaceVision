"""REST endpoints for session lifecycle management."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from core.exceptions import SessionLimitReached, SessionNotFound
from schemas.session import SessionCreate, SessionInfo, SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate, request: Request) -> SessionResponse:
    """Start a new live pose-analysis session."""
    manager = request.app.state.session_manager
    loop = asyncio.get_running_loop()
    try:
        session = manager.create_session(
            device_index=body.device_index,
            loop=loop,
        )
    except SessionLimitReached as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return SessionResponse(
        session_id=session.session_id,
        status=session.status,
        created_at=session.created_at,
    )


@router.get("", response_model=list[SessionInfo])
async def list_sessions(request: Request) -> list[SessionInfo]:
    """List all active sessions."""
    manager = request.app.state.session_manager
    return manager.list_sessions()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, request: Request) -> SessionInfo:
    """Get status and stats for a specific session."""
    manager = request.app.state.session_manager
    try:
        s = manager.get_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return SessionInfo(
        session_id=s.session_id,
        status=s.status,
        created_at=s.created_at,
        frame_count=s.frame_count,
        fps=s.fps,
    )


@router.delete("/{session_id}")
async def stop_session(session_id: str, request: Request) -> dict:
    """Stop and remove a session."""
    manager = request.app.state.session_manager
    try:
        manager.stop_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"stopped": True, "session_id": session_id}
