"""Pydantic schemas for session management API."""

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Request body for creating a new live session."""

    device_index: int = Field(default=0, ge=0, le=10)


class SessionResponse(BaseModel):
    """Returned when a session is created."""

    session_id: str
    status: str
    created_at: datetime


class SessionInfo(BaseModel):
    """Detailed information about a running session."""

    session_id: str
    status: str  # "starting" | "running" | "stopped" | "error"
    created_at: datetime
    frame_count: int = 0
    fps: float = 0.0
